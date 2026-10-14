"""Il registry: che cosa esiste.

E' il ponte fra i plugin installati e chi deve fare un piano:

    plugin installati  ->  vocabolario disponibile  ->  planner  ->  graph

Una sola domanda, e nessun'altra: **cosa esiste?** Non «quale scegliere» — che
e' del resolver — e non «cosa vuol dire»: il registry non sa che cosa sia una
casa, un animale o un umanoide, e non deve saperlo. Sa che il componente
`dragon:head` fornisce `head`, espone un innesto `neck_mount` e porta i tag
`{drago, rettile, testa}`. Chi legge quei nomi decide cosa significano.

## Niente `if plugin == "humanoid"`

E' la regola che tiene in piedi tutta l'architettura. Il registry carica
dinamicamente cio' che trova in una cartella; se domani qualcuno mette un
plugin che costruisce cristalli quantici, il registry lo indicizza senza che
una riga del core cambi. Un test lo verifica caricando un plugin che il core
non ha mai visto.

## Fonte di verita'

I file: `plugin.json` piu' i moduli Python che dichiara. Il registry e' un
**indice in memoria**, ricostruibile in qualunque momento. Niente database,
niente cache su disco, niente scoperta remota: sarebbero un secondo punto di
verita' da tenere allineato, e oggi non servono a niente.

## Un plugin rotto non ne rompe altri

Il caricamento e' isolato per plugin: un manifest illeggibile o un modulo che
esplode producono una diagnosi e vengono scartati, gli altri si caricano.
Serve adesso, perche' i plugin sono nostri e sbagliamo; servira' di piu' il
giorno in cui non saranno nostri.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from app.core.capability import Capability
from app.core.component import Component
from app.core.errors import Report
from app.core.archetypes import (ArchetypeSpec, ImplementationBinding,
                                  ProfileSpec)
from app.core.material import MaterialSpec
from app.core.layout import LayoutPolicy, default_policies
from app.core.params import ParamSpec
from app.core.structural import (INSTANCE_COUNT, MAX_STRUCTURAL_COUNT,
                                 StructuralTraitRule, StructuralTraitSpec)
from app.core.traits import TraitRule, TraitSpec
from app.core.vocabulary import EffectSpec, StyleProfile

MANIFEST = "plugin.json"
SEPARATOR = ":"

# Caratteri ammessi in un id di plugin. Stretti di proposito: un id finisce
# dentro un riferimento qualificato, e "a:b/c" non sarebbe piu' spezzabile.
_ID_OK = set("abcdefghijklmnopqrstuvwxyz0123456789_-")

_contatore = 0                  # nomi di modulo univoci, per caricamenti ripetuti


class RegistryError(RuntimeError):
    """Uso sbagliato dell'API. I problemi dei plugin non sollevano: si annotano."""


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #
@dataclass
class PluginInfo:
    """Il manifest, letto e validato. Niente di piu'.

    `sources` sono i file Python dichiarati: e' li' che stanno i componenti,
    perche' costruire geometria richiede codice e nessuno schema JSON puo'
    sostituirlo. Il manifest dice **quali file**, non cosa contengono: cosi'
    aggiungere un componente non obbliga a tenere allineate due descrizioni.
    """

    id: str
    version: str = "0.0.0"
    name: str = ""
    description: str = ""
    author: str = ""
    license: str = ""
    homepage: str = ""
    tags: frozenset[str] = field(default_factory=frozenset)
    dependencies: tuple[str, ...] = ()
    capabilities: tuple[Capability, ...] = ()      # quelle che il plugin introduce
    notes: dict[str, str] = field(default_factory=dict)   # capability -> descrizione
    metadata: dict[str, Any] = field(default_factory=dict)
    sources: tuple[str, ...] = ()
    path: Path | None = None

    def __post_init__(self) -> None:
        self.tags = frozenset(self.tags)
        self.name = self.name or self.id

    def describe(self) -> str:
        return "%s %s (%s)" % (self.id, self.version, self.name)


@dataclass
class CapabilityInfo:
    """Chi offre e chi accetta una capability. Costruito su richiesta."""

    name: str
    description: str = ""
    tags: frozenset[str] = field(default_factory=frozenset)
    providers: tuple[str, ...] = ()      # componenti che **sono** questa cosa
    mounts: tuple[str, ...] = ()         # componenti che la **accettano**
    plugins: tuple[str, ...] = ()

    @property
    def known(self) -> bool:
        return bool(self.providers or self.mounts or self.description)

    def describe(self) -> str:
        return "%s: %d forniscono, %d accettano" % (self.name, len(self.providers),
                                                    len(self.mounts))


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
class Registry:
    """Indice in memoria di tutto cio' che e' installato.

    Registrazione, ricerca e scoperta sono tre cose separate: si registra a
    mano (test, plugin incorporati), si scopre da una cartella, si interroga
    sempre allo stesso modo.
    """

    def __init__(self) -> None:
        self.report = Report()
        self._plugins: dict[str, PluginInfo] = {}
        self._components: dict[str, Component] = {}
        self._effects: dict[str, EffectSpec] = {}
        self._traits: dict[str, TraitSpec] = {}
        self._trait_aliases: dict[str, set[str]] = {}
        self._trait_rules: dict[str, TraitRule] = {}
        self._structural_traits: dict[str, StructuralTraitSpec] = {}
        self._structural_trait_aliases: dict[str, set[str]] = {}
        self._structural_trait_rules: dict[str, StructuralTraitRule] = {}
        self._layout_policies: dict[str, LayoutPolicy] = {
            policy.id: policy for policy in default_policies()
        }
        self._structural_traits[INSTANCE_COUNT] = StructuralTraitSpec(
            id=INSTANCE_COUNT, aliases=("instance_count",),
            description="ensure N instances of a compatible semantic child",
            value=ParamSpec(1, min=0, max=MAX_STRUCTURAL_COUNT),
            max_count=MAX_STRUCTURAL_COUNT, owner="core")
        self._styles: dict[str, StyleProfile] = {}
        self._archetypes: dict[str, ArchetypeSpec] = {}
        self._archetype_aliases: dict[str, set[str]] = {}
        self._profiles: dict[str, ProfileSpec] = {}
        self._profile_aliases: dict[str, set[str]] = {}
        self._implementation_bindings: dict[str, ImplementationBinding] = {}
        self._semantic_checked = False
        # I materiali stanno per **nome nudo**: `skin` e' un nome condiviso,
        # non il pezzo di un plugin. Chi lo dichiara per primo lo definisce.
        self._materials: dict[str, MaterialSpec] = {}
        self._material_source: dict[str, str] = {}
        self._declared: dict[str, dict[str, Any]] = {}
        self._paths: dict[str, str] = {}          # plugin id -> cartella caricata
        self._frozen = False

    # ------------------------------------------------------------ stabilita' #
    @property
    def frozen(self) -> bool:
        return self._frozen

    def freeze(self) -> "Registry":
        """Chiude il registry alle scritture.

        Durante una generazione il vocabolario deve stare fermo: se un
        componente potesse registrarne altri mentre si costruisce, lo stesso
        piano darebbe risultati diversi a seconda dell'ordine di espansione.
        """
        self.verify()
        self._link_styles()
        self._frozen = True
        return self

    def _link_styles(self) -> None:
        """Collega ogni stile a quello da cui dichiara di discendere.

        Qui e non alla registrazione, perche' un plugin puo' estendere lo stile
        di un altro plugin che verra' caricato dopo. Un `extends` che non trova
        niente resta una nota: il profilo vale per i numeri che dichiara.
        """
        for profilo in self._styles.values():
            if not profilo.extends or profilo.base is not None:
                continue
            padre = self._lookup(self._styles, profilo.extends)
            if padre is None:
                self.report.note("STYLE_BASE_MISSING",
                                 "lo stile '%s' estende '%s', che non e' installato"
                                 % (profilo.id, profilo.extends),
                                 alternatives=[s.id for s in self.styles()][:6])
                continue
            profilo.base = padre

    def _guard(self) -> None:
        if self._frozen:
            raise RegistryError("il registry e' chiuso: non si registra durante "
                                "una generazione")

    # ---------------------------------------------------------- registrazione #
    def register_plugin(self, info: PluginInfo) -> bool:
        self._guard()
        self._semantic_checked = False
        if not info.id:
            self.report.add("INVALID_MANIFEST", "plugin senza id")
            return False
        if info.id in self._plugins:
            self.report.add("DUPLICATE_PLUGIN",
                            "plugin gia' installato: '%s'" % info.id,
                            where=str(info.path or ""),
                            why="l'id di un plugin e' unico nell'installazione")
            return False
        self._plugins[info.id] = info
        for capacita in info.capabilities:
            voce = self._declared.setdefault(capacita.name,
                                             {"description": "", "tags": set(),
                                              "plugins": set()})
            voce["tags"] |= set(capacita.tags)
            voce["plugins"].add(info.id)
            if info.notes.get(capacita.name) and not voce["description"]:
                voce["description"] = info.notes[capacita.name]
        return True

    def register_component(self, component: Component, plugin_id: str = "") -> bool:
        return self._register(component, self._components, plugin_id,
                              "DUPLICATE_COMPONENT", "componente")

    def register_effect(self, effect: EffectSpec, plugin_id: str = "") -> bool:
        return self._register(effect, self._effects, plugin_id,
                              "DUPLICATE_EFFECT", "effetto")

    def register_trait(self, trait: TraitSpec, plugin_id: str = "") -> bool:
        self._guard()
        if not trait.id or SEPARATOR not in trait.id:
            self.report.add("INVALID_TRAIT",
                            "trait senza id canonico: '%s'" % trait.id,
                            why="serve namespace:name")
            return False
        if trait.id in self._traits:
            self.report.add("DUPLICATE_TRAIT",
                            "trait gia' registrato: '%s'" % trait.id)
            return False
        self._traits[trait.id] = trait
        for alias in trait.aliases:
            if alias and SEPARATOR not in alias:
                self._trait_aliases.setdefault(alias, set()).add(trait.id)
        return True

    def register_trait_rule(self, rule: TraitRule, plugin_id: str = "") -> bool:
        self._guard()
        if not self._qualify(rule, plugin_id, "trait rule"):
            return False
        if rule.id in self._trait_rules:
            self.report.add("DUPLICATE_TRAIT_RULE",
                            "trait rule gia' registrata: '%s'" % rule.id)
            return False
        self._trait_rules[rule.id] = rule
        return True

    def register_structural_trait(self, trait: StructuralTraitSpec,
                                  plugin_id: str = "") -> bool:
        self._guard()
        if not trait.id or SEPARATOR not in trait.id:
            self.report.add("INVALID_STRUCTURAL_TRAIT",
                            "structural trait senza id canonico: '%s'" % trait.id,
                            why="serve namespace:name")
            return False
        if trait.id in self._structural_traits:
            self.report.add("DUPLICATE_STRUCTURAL_TRAIT",
                            "structural trait gia' registrato: '%s'" % trait.id)
            return False
        self._structural_traits[trait.id] = trait
        for alias in trait.aliases:
            if alias and SEPARATOR not in alias:
                self._structural_trait_aliases.setdefault(alias, set()).add(trait.id)
        return True

    def register_structural_trait_rule(self, rule: StructuralTraitRule,
                                       plugin_id: str = "") -> bool:
        self._guard()
        if not self._qualify(rule, plugin_id, "structural trait rule"):
            return False
        if rule.id in self._structural_trait_rules:
            self.report.add("DUPLICATE_STRUCTURAL_TRAIT_RULE",
                            "structural trait rule gia' registrata: '%s'" % rule.id)
            return False
        self._structural_trait_rules[rule.id] = rule
        return True

    def register_layout_policy(self, policy: LayoutPolicy,
                               plugin_id: str = "") -> bool:
        self._guard()
        if not self._qualify(policy, plugin_id, "layout policy"):
            return False
        if policy.id in self._layout_policies:
            self.report.add("DUPLICATE_LAYOUT_POLICY",
                            "layout policy gia' registrata: '%s'" % policy.id)
            return False
        self._layout_policies[policy.id] = policy
        return True

    def register_style(self, style: StyleProfile, plugin_id: str = "") -> bool:
        return self._register(style, self._styles, plugin_id,
                              "DUPLICATE_STYLE", "stile")

    def register_archetype(self, archetype: ArchetypeSpec,
                           plugin_id: str = "") -> bool:
        self._guard()
        if not self._qualify_semantic(archetype, plugin_id, "archetype"):
            return False
        if archetype.id in self._archetypes:
            self.report.add("DUPLICATE_ARCHETYPE",
                            "Archetype gia' registrato: '%s'" % archetype.id)
            return False
        archetype.owner = archetype.owner or plugin_id
        archetype.parents = tuple(self._qualify_ref(v, plugin_id)
                                   for v in archetype.parents)
        self._archetypes[archetype.id] = archetype
        for alias in archetype.aliases:
            if alias and SEPARATOR not in alias:
                self._archetype_aliases.setdefault(alias, set()).add(archetype.id)
        self._semantic_checked = False
        return True

    def register_profile(self, profile: ProfileSpec, plugin_id: str = "") -> bool:
        self._guard()
        if not self._qualify_semantic(profile, plugin_id, "profile"):
            return False
        if profile.id in self._profiles:
            self.report.add("DUPLICATE_PROFILE",
                            "Profile gia' registrato: '%s'" % profile.id)
            return False
        profile.owner = profile.owner or plugin_id
        profile.archetypes = tuple(self._qualify_ref(v, plugin_id)
                                   for v in profile.archetypes)
        profile.includes = tuple(self._qualify_ref(v, plugin_id)
                                 for v in profile.includes)
        self._profiles[profile.id] = profile
        for alias in profile.aliases:
            if alias and SEPARATOR not in alias:
                self._profile_aliases.setdefault(alias, set()).add(profile.id)
        self._semantic_checked = False
        return True

    def register_implementation_binding(self, binding: ImplementationBinding,
                                         plugin_id: str = "") -> bool:
        self._guard()
        if not self._qualify_semantic(binding, plugin_id, "implementation binding"):
            return False
        if binding.id in self._implementation_bindings:
            self.report.add("DUPLICATE_IMPLEMENTATION_BINDING",
                            "binding gia' registrato: '%s'" % binding.id)
            return False
        binding.owner = binding.owner or plugin_id
        # The implementation may belong to another plugin: a third party can
        # bind an existing Component without changing its original plugin.
        binding.implementation = self._qualify_ref(binding.implementation, plugin_id)
        binding.supported_archetypes = tuple(
            self._qualify_ref(v, plugin_id) for v in binding.supported_archetypes)
        self._implementation_bindings[binding.id] = binding
        self._semantic_checked = False
        return True

    def register_material(self, material: MaterialSpec,
                          plugin_id: str = "") -> bool:
        """Un materiale si registra per **nome nudo**, non qualificato.

        `skin` e' un nome che piu' plugin usano volendo la stessa cosa, come
        una capability: qualificarlo darebbe `humanoid:skin` e `creature:skin`,
        cioe' due pelli diverse dove ne serviva una. Chi lo dichiara per primo
        lo definisce; chi lo ridichiara **diverso** viene riferito, perche' un
        colore che cambia a seconda dell'ordine di caricamento e' il genere di
        cosa che si scopre guardando il modello.
        """
        self._guard()
        if not material.name:
            self.report.add("INVALID_MANIFEST", "materiale senza nome")
            return False
        gia = self._materials.get(material.name)
        if gia is not None:
            if gia.base_color != material.base_color:
                self.report.note(
                    "MATERIAL_REDECLARED",
                    "'%s' e' gia' dichiarato come %s" % (material.name,
                                                         gia.base_color),
                    where=plugin_id,
                    why="vale la prima dichiarazione: %s resta fuori"
                        % material.base_color)
            return False
        self._materials[material.name] = material
        self._material_source[material.name] = plugin_id
        return True

    def _register(self, item, table: dict, plugin_id: str, code: str,
                  what: str) -> bool:
        self._guard()
        self._semantic_checked = False
        if not self._qualify(item, plugin_id, what):
            return False
        if item.id in table:
            self.report.add(code, "%s gia' registrato: '%s'" % (what, item.id),
                            why="in una stessa installazione un id qualificato "
                                "identifica una cosa sola")
            return False
        table[item.id] = item
        return True

    def _qualify(self, item, plugin_id: str, what: str) -> bool:
        """Porta l'id nella forma `plugin:nome`, o rifiuta.

        Un plugin puo' scrivere `Component(id="head")` e lasciare che sia il
        registry a qualificarlo. Non puo' invece dichiarare `altro:head`:
        occupare il namespace di un altro plugin renderebbe i riferimenti
        inaffidabili.
        """
        if SEPARATOR not in item.id:
            if not plugin_id:
                self.report.add("INVALID_MANIFEST",
                                "%s '%s' senza plugin" % (what, item.id),
                                why="serve un id qualificato 'plugin:nome'")
                return False
            item.id = "%s%s%s" % (plugin_id, SEPARATOR, item.id)
            return True
        if plugin_id and item.id.partition(SEPARATOR)[0] != plugin_id:
            self.report.add("COMPONENT_ID_MISMATCH",
                            "%s '%s' dichiarato dal plugin '%s'"
                            % (what, item.id, plugin_id),
                            why="un plugin non puo' registrare nel namespace di "
                                "un altro")
            return False
        return True

    def _qualify_semantic(self, item, plugin_id: str, what: str) -> bool:
        if not getattr(item, "id", ""):
            self.report.add("INVALID_%s" % what.upper().replace(" ", "_"),
                            "%s senza id" % what)
            return False
        if SEPARATOR not in item.id:
            if not plugin_id:
                self.report.add("INVALID_%s" % what.upper().replace(" ", "_"),
                                "%s '%s' senza namespace" % (what, item.id),
                                why="serve un id 'plugin:nome'")
                return False
            item.id = "%s%s%s" % (plugin_id, SEPARATOR, item.id)
        elif plugin_id and item.id.partition(SEPARATOR)[0] != plugin_id:
            self.report.add("SEMANTIC_ID_MISMATCH",
                            "%s '%s' dichiarato dal plugin '%s'"
                            % (what, item.id, plugin_id),
                            why="un metadata object non puo' occupare un namespace diverso")
            return False
        return True

    @staticmethod
    def _qualify_ref(value: str, plugin_id: str) -> str:
        value = str(value or "").strip()
        if value and SEPARATOR not in value and plugin_id:
            return "%s%s%s" % (plugin_id, SEPARATOR, value)
        return value

    # -------------------------------------------------------------- scoperta #
    def load_directory(self, path) -> Report:
        """Scopre i plugin in una cartella. Ognuno isolato dagli altri."""
        self._guard()
        inizio = len(self.report)
        base = Path(path)

        if not base.is_dir():
            self.report.add("PLUGIN_DIR_MISSING", "cartella inesistente: %s" % base)
            return self._since(inizio)

        if (base / MANIFEST).is_file():
            self.load_plugin(base)
        else:
            for voce in sorted(base.iterdir()):
                # una cartella senza manifest non e' un errore: e' solo altro
                if voce.is_dir() and (voce / MANIFEST).is_file():
                    self.load_plugin(voce)

        self.verify()
        return self._since(inizio)

    def load_plugin(self, path) -> PluginInfo | None:
        """Carica un singolo plugin. Restituisce `None` se e' stato scartato."""
        self._guard()
        cartella = Path(path)
        manifesto = cartella / MANIFEST
        if not manifesto.is_file():
            self.report.add("MANIFEST_MISSING", "manca %s" % MANIFEST,
                            where=str(cartella))
            return None

        info = self._read_manifest(manifesto)
        if info is None:
            return None

        gia = self._plugins.get(info.id)
        if gia is not None:
            if self._paths.get(info.id) == str(cartella.resolve()):
                # ricaricare la stessa cartella non deve cambiare niente
                self.report.note("PLUGIN_ALREADY_LOADED",
                                 "plugin gia' caricato: '%s'" % info.id,
                                 where=str(cartella))
                return gia
            self.report.add("DUPLICATE_PLUGIN",
                            "due plugin con lo stesso id: '%s'" % info.id,
                            where=str(cartella),
                            why="gia' caricato da %s" % self._paths.get(info.id, "?"))
            return None

        # si carica tutto **prima** di registrare qualcosa: un modulo che
        # esplode a meta' non deve lasciare mezzo vocabolario nell'indice
        raccolti: list = []
        for relativo in info.sources:
            file = cartella / relativo
            try:
                modulo = _import_file(file, info.id)
            except Exception as exc:                   # noqa: BLE001 - isolamento
                self.report.add("PLUGIN_LOAD_FAILED",
                                "plugin '%s' scartato: %s" % (info.id, exc),
                                where=str(file),
                                why="%s durante il caricamento" % type(exc).__name__)
                return None
            raccolti.extend(_harvest(modulo))

        if not self.register_plugin(info):
            return None
        self._paths[info.id] = str(cartella.resolve())

        # ordine stabile: i materiali si chiamano per nome, tutto il resto per id
        for item in sorted(raccolti, key=lambda o: (type(o).__name__,
                                                    getattr(o, "id", "")
                                                    or getattr(o, "name", ""))):
            if isinstance(item, Component):
                self.register_component(item, info.id)
            elif isinstance(item, EffectSpec):
                self.register_effect(item, info.id)
            elif isinstance(item, TraitSpec):
                self.register_trait(item, info.id)
            elif isinstance(item, TraitRule):
                self.register_trait_rule(item, info.id)
            elif isinstance(item, StructuralTraitSpec):
                self.register_structural_trait(item, info.id)
            elif isinstance(item, StructuralTraitRule):
                self.register_structural_trait_rule(item, info.id)
            elif isinstance(item, LayoutPolicy):
                self.register_layout_policy(item, info.id)
            elif isinstance(item, StyleProfile):
                self.register_style(item, info.id)
            elif isinstance(item, MaterialSpec):
                self.register_material(item, info.id)
            elif isinstance(item, ArchetypeSpec):
                self.register_archetype(item, info.id)
            elif isinstance(item, ProfileSpec):
                self.register_profile(item, info.id)
            elif isinstance(item, ImplementationBinding):
                self.register_implementation_binding(item, info.id)

        if not raccolti:
            self.report.note("PLUGIN_EMPTY",
                             "il plugin '%s' non dichiara niente" % info.id,
                             where=str(cartella))
        return info

    def _read_manifest(self, manifesto: Path) -> PluginInfo | None:
        cartella = manifesto.parent
        try:
            dati = json.loads(manifesto.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            self.report.add("INVALID_MANIFEST", "manifest illeggibile: %s" % exc,
                            where=str(manifesto))
            return None
        if not isinstance(dati, dict):
            self.report.add("INVALID_MANIFEST", "il manifest non e' un oggetto",
                            where=str(manifesto))
            return None

        id = str(dati.get("id", "")).strip()
        if not id or set(id) - _ID_OK:
            self.report.add("INVALID_MANIFEST",
                            "id di plugin non valido: %r" % dati.get("id"),
                            where=str(manifesto),
                            why="minuscole, cifre, '_' e '-'; mai vuoto e mai "
                                "con '%s'" % SEPARATOR)
            return None

        version = str(dati.get("version", "")).strip()
        if not version:
            self.report.add("INVALID_MANIFEST", "manca la versione",
                            where=str(manifesto),
                            why="la versione si conserva anche se nessuno la "
                                "risolve ancora")
            return None

        dipendenze = dati.get("dependencies", [])
        if not isinstance(dipendenze, list) or \
                any(not isinstance(d, str) or not d for d in dipendenze):
            self.report.add("INVALID_DEPENDENCY",
                            "dipendenze malformate in '%s'" % id,
                            where=str(manifesto),
                            why="serve una lista di id di plugin")
            return None

        sorgenti: list[str] = []
        for chiave in ("components", "effects", "styles", "materials", "traits",
                       "archetypes", "profiles", "bindings"):
            valore = dati.get(chiave, [])
            if not isinstance(valore, list):
                self.report.add("INVALID_MANIFEST",
                                "'%s' deve essere una lista" % chiave,
                                where=str(manifesto))
                return None
            for voce in valore:
                relativo = voce.get("module", "") if isinstance(voce, dict) else voce
                if not isinstance(relativo, str) or not relativo:
                    self.report.add("INVALID_MANIFEST",
                                    "voce non valida in '%s': %r" % (chiave, voce),
                                    where=str(manifesto),
                                    why="serve il percorso di un file Python")
                    return None
                if relativo not in sorgenti:
                    sorgenti.append(relativo)

        for relativo in sorgenti:
            if not (cartella / relativo).is_file():
                self.report.add("MISSING_COMPONENT_FILE",
                                "file dichiarato e assente: %s" % relativo,
                                where=str(cartella),
                                why="un plugin incompleto vale meno di un plugin "
                                    "assente: si carica a meta' e sbaglia dopo")
                return None

        capacita, note = [], {}
        for voce in dati.get("capabilities", []) or []:
            if isinstance(voce, str):
                capacita.append(Capability(voce))
            elif isinstance(voce, dict) and voce.get("name"):
                capacita.append(Capability(str(voce["name"]),
                                           frozenset(voce.get("tags", []) or [])))
                if voce.get("description"):
                    note[str(voce["name"])] = str(voce["description"])

        return PluginInfo(
            id=id, version=version,
            name=str(dati.get("name", "")), description=str(dati.get("description", "")),
            author=str(dati.get("author", "")), license=str(dati.get("license", "")),
            homepage=str(dati.get("homepage", "")),
            tags=frozenset(dati.get("tags", []) or []),
            dependencies=tuple(dipendenze), capabilities=tuple(capacita), notes=note,
            metadata=dict(dati.get("metadata", {}) or {}),
            sources=tuple(sorgenti), path=cartella)

    # ------------------------------------------------------------- verifiche #
    def verify(self) -> Report:
        """Controlli che hanno senso solo a caricamento finito.

        Le dipendenze si verificano qui e non durante il caricamento: 'alfa
        dipende da beta' non e' un errore se beta arriva dopo, in ordine
        alfabetico.
        """
        inizio = len(self.report)
        for info in self.plugins():
            for dipendenza in info.dependencies:
                if dipendenza not in self._plugins:
                    self.report.warn(
                        "DEPENDENCY_MISSING",
                        "'%s' dipende da '%s', che non e' installato"
                        % (info.id, dipendenza), where=info.id,
                        alternatives=sorted(self._plugins)[:6])
        if not self._semantic_checked:
            self._verify_archetypes()
            self._verify_profiles()
            self._verify_bindings()
            self._semantic_checked = True
        return self._since(inizio)

    def _verify_archetypes(self) -> None:
        for alias, ids in sorted(self._archetype_aliases.items()):
            if len(ids) > 1:
                self._semantic_add_once(
                    "ARCHETYPE_ALIAS_AMBIGUOUS",
                    "alias Archetype ambiguo '%s': %s" % (alias, ", ".join(sorted(ids))),
                    where=alias)
        for spec in self.archetypes():
            for parent in spec.parents:
                if self._archetypes.get(parent) is None:
                    self._semantic_add_once(
                        "ARCHETYPE_PARENT_MISSING",
                        "Archetype '%s' richiede il parent '%s'" % (spec.id, parent),
                        where=spec.id, alternatives=self.archetype_ids())
            for request in spec.default_traits:
                trait_id = str(getattr(request, "trait", "") or
                               (request.get("trait", "")
                                if isinstance(request, dict) else ""))
                if trait_id and self.trait(trait_id) is None:
                    self._semantic_add_once(
                        "ARCHETYPE_TRAIT_MISSING",
                        "Archetype '%s' usa Trait '%s' non installato"
                        % (spec.id, trait_id), where=spec.id)
            for request in spec.structural_expectations:
                trait_id = str(getattr(request, "trait", "") or
                               (request.get("trait", "")
                                if isinstance(request, dict) else ""))
                if trait_id and self.structural_trait(trait_id) is None:
                    self._semantic_add_once(
                        "ARCHETYPE_STRUCTURAL_TRAIT_MISSING",
                        "Archetype '%s' usa Structural Trait '%s' non installato"
                        % (spec.id, trait_id), where=spec.id)

        visiting: set[str] = set()
        visited: set[str] = set()

        def walk(aid: str, stack: tuple[str, ...] = ()) -> None:
            if aid in visiting:
                ciclo = stack[stack.index(aid):] + (aid,) if aid in stack else (aid,)
                self._semantic_add_once(
                    "ARCHETYPE_CYCLE", "ciclo Archetype: %s" % " -> ".join(ciclo),
                    where=aid)
                return
            if aid in visited:
                return
            visiting.add(aid)
            spec = self._archetypes.get(aid)
            if spec is not None:
                for parent in sorted(spec.parents):
                    if parent in self._archetypes:
                        walk(parent, stack + (aid,))
            visiting.remove(aid)
            visited.add(aid)

        for aid in sorted(self._archetypes):
            walk(aid)

    def _verify_profiles(self) -> None:
        for alias, ids in sorted(self._profile_aliases.items()):
            if len(ids) > 1:
                self._semantic_add_once(
                    "PROFILE_ALIAS_AMBIGUOUS",
                    "alias Profile ambiguo '%s': %s" % (alias, ", ".join(sorted(ids))),
                    where=alias)
        for profile in self.profiles():
            for aid in profile.archetypes:
                if self._archetypes.get(aid) is None:
                    self._semantic_add_once(
                        "PROFILE_ARCHETYPE_MISSING",
                        "Profile '%s' richiede l'Archetype '%s'"
                        % (profile.id, aid), where=profile.id,
                        alternatives=self.archetype_ids())
            for included in profile.includes:
                if self._profiles.get(included) is None:
                    self._semantic_add_once(
                        "PROFILE_INCLUDE_MISSING",
                        "Profile '%s' include '%s', che non e' installato"
                        % (profile.id, included), where=profile.id,
                        alternatives=self.profile_ids())
            for request in profile.default_traits:
                trait_id = str(getattr(request, "trait", "") or
                               (request.get("trait", "")
                                if isinstance(request, dict) else ""))
                if trait_id and self.trait(trait_id) is None:
                    self._semantic_add_once(
                        "PROFILE_TRAIT_MISSING",
                        "Profile '%s' usa Trait '%s' non installato"
                        % (profile.id, trait_id), where=profile.id)
            for request in profile.structural_defaults:
                trait_id = str(getattr(request, "trait", "") or
                               (request.get("trait", "")
                                if isinstance(request, dict) else ""))
                if trait_id and self.structural_trait(trait_id) is None:
                    self._semantic_add_once(
                        "PROFILE_STRUCTURAL_TRAIT_MISSING",
                        "Profile '%s' usa Structural Trait '%s' non installato"
                        % (profile.id, trait_id), where=profile.id)

        visiting: set[str] = set()
        visited: set[str] = set()

        def walk(pid: str, stack: tuple[str, ...] = ()) -> None:
            if pid in visiting:
                ciclo = stack[stack.index(pid):] + (pid,) if pid in stack else (pid,)
                self._semantic_add_once(
                    "PROFILE_CYCLE", "ciclo Profile: %s" % " -> ".join(ciclo),
                    where=pid)
                return
            if pid in visited:
                return
            visiting.add(pid)
            profile = self._profiles.get(pid)
            if profile is not None:
                for included in sorted(profile.includes):
                    if included in self._profiles:
                        walk(included, stack + (pid,))
            visiting.remove(pid)
            visited.add(pid)

        for pid in sorted(self._profiles):
            walk(pid)

    def _verify_bindings(self) -> None:
        for binding in self.implementation_bindings():
            if self.component(binding.implementation) is None:
                self._semantic_add_once(
                    "BINDING_IMPLEMENTATION_MISSING",
                    "binding '%s' indica '%s', che non e' installato"
                    % (binding.id, binding.implementation), where=binding.id,
                    alternatives=[c.id for c in self.components()][:8])
            for aid in binding.supported_archetypes:
                if self.archetype(aid) is None:
                    self._semantic_add_once(
                        "BINDING_ARCHETYPE_MISSING",
                        "binding '%s' indica Archetype '%s' non installato"
                        % (binding.id, aid), where=binding.id,
                        alternatives=self.archetype_ids())

    def _semantic_add_once(self, code: str, message: str, **kwargs) -> None:
        where = kwargs.get("where", "")
        if any(d.code == code and d.where == where and d.message == message
               for d in self.report.entries):
            return
        self.report.add(code, message, **kwargs)

    def _since(self, inizio: int) -> Report:
        return Report(list(self.report.entries[inizio:]))

    # -------------------------------------------------------------- ricerche #
    def plugin(self, id: str) -> PluginInfo | None:
        return self._plugins.get(id)

    def plugins(self) -> list[PluginInfo]:
        return [self._plugins[k] for k in sorted(self._plugins)]

    def component(self, id: str) -> Component | None:
        return self._lookup(self._components, id)

    def components(self, plugin: str = "", style: str = "",
                   tags: Iterable[str] = ()) -> list[Component]:
        volute = frozenset(tags)
        return [c for c in self._all(self._components)
                if (not plugin or c.plugin == plugin)
                and (not style or c.supports_style(style))
                and volute <= c.tags]

    def archetype(self, id: str) -> ArchetypeSpec | None:
        return self._semantic_lookup(self._archetypes, self._archetype_aliases, id)

    def archetypes(self) -> list[ArchetypeSpec]:
        return self._all(self._archetypes)

    def archetype_ids(self) -> list[str]:
        return sorted(self._archetypes)

    def archetype_ambiguous(self, alias: str) -> bool:
        return SEPARATOR not in alias and len(self._archetype_aliases.get(alias, set())) > 1

    def profile(self, id: str) -> ProfileSpec | None:
        return self._semantic_lookup(self._profiles, self._profile_aliases, id)

    def profiles(self) -> list[ProfileSpec]:
        return self._all(self._profiles)

    def profile_ids(self) -> list[str]:
        return sorted(self._profiles)

    def profile_ambiguous(self, alias: str) -> bool:
        return SEPARATOR not in alias and len(self._profile_aliases.get(alias, set())) > 1

    def implementation_binding(self, id: str) -> ImplementationBinding | None:
        return self._lookup(self._implementation_bindings, id)

    def implementation_bindings(self, archetype: str = "") -> list[ImplementationBinding]:
        if not archetype:
            return self._all(self._implementation_bindings)
        return [b for b in self._all(self._implementation_bindings)
                if archetype in b.supported_archetypes]

    def concept_index(self) -> list[dict[str, Any]]:
        """Compact global index: no requirements, profiles or bindings."""
        return [{"id": a.id, "aliases": list(a.aliases),
                 "description": str(a.description)[:160]}
                for a in self.archetypes()]

    def effect(self, id: str) -> EffectSpec | None:
        return self._lookup(self._effects, id)

    def effects(self, scope: str = "", plugin: str = "",
                tags: Iterable[str] = ()) -> list[EffectSpec]:
        volute = frozenset(tags)
        return [e for e in self._all(self._effects)
                if (not plugin or e.plugin == plugin)
                and (not scope or e.fits_scope(scope))
                and volute <= e.tags]

    def effects_for(self, capability: str = "", scope: str = "") -> list[EffectSpec]:
        """Gli effetti che dichiarano di avere senso su questa capability."""
        return [e for e in self.effects(scope=scope) if e.fits(capability)]

    def trait(self, id: str) -> TraitSpec | None:
        if id in self._traits:
            return self._traits[id]
        if SEPARATOR in id:
            return None
        ids = self._trait_aliases.get(id, set())
        if len(ids) == 1:
            return self._traits[next(iter(ids))]
        return None

    def traits(self) -> list[TraitSpec]:
        return self._all(self._traits)

    def trait_ambiguous(self, alias: str) -> bool:
        return SEPARATOR not in alias and len(self._trait_aliases.get(alias, set())) > 1

    def trait_rules(self, trait: str = "") -> list[TraitRule]:
        spec = self.trait(trait) if trait else None
        canonical = spec.id if spec is not None else trait
        return [r for r in self._all(self._trait_rules)
                if not canonical or r.trait == canonical]

    def structural_trait(self, id: str) -> StructuralTraitSpec | None:
        found = self._lookup(self._structural_traits, id)
        if found is not None or SEPARATOR in id:
            return found
        ids = self._structural_trait_aliases.get(id, set())
        if len(ids) == 1:
            return self._structural_traits[next(iter(ids))]
        return None

    def structural_traits(self) -> list[StructuralTraitSpec]:
        return self._all(self._structural_traits)

    def structural_trait_rules(self, trait: str = "") -> list[StructuralTraitRule]:
        spec = self.structural_trait(trait) if trait else None
        canonical = spec.id if spec is not None else trait
        return [r for r in self._all(self._structural_trait_rules)
                if not canonical or r.trait == canonical]

    def layout_policy(self, id: str) -> LayoutPolicy | None:
        return self._lookup(self._layout_policies, id)

    def layout_policies(self) -> list[LayoutPolicy]:
        return self._all(self._layout_policies)

    def style(self, id: str) -> StyleProfile | None:
        return self._lookup(self._styles, id)

    def styles(self) -> list[StyleProfile]:
        return self._all(self._styles)

    # ---------------------------------------------------------- materiali #
    def material(self, name: str) -> MaterialSpec:
        """L'aspetto di una superficie. Sempre uno: un nome sconosciuto e'
        un grigio, non un errore — un modello grigio e' meglio di un modello
        mancante."""
        from app.core.material import default_material

        return self._materials.get(name) or default_material(name)

    def materials(self) -> list[MaterialSpec]:
        return [self._materials[n] for n in sorted(self._materials)]

    def knows_material(self, name: str) -> bool:
        return name in self._materials

    # --------------------------------------------------------- capability #
    def providers(self, capability: str = "", side: str = "",
                  tags: Iterable[str] = (), style: str = "",
                  plugin: str = "") -> list[Component]:
        """Chi puo' servire questa capability. **Tutti**, non il migliore.

        Un componente la serve in due modi diversi e ugualmente legittimi: la
        **e'** (`provides`), oppure la **accetta** (`mounts`). Tenerli in due
        query separate obbligherebbe chi cerca a sapere in anticipo quale dei
        due casi sta cercando, che e' proprio l'informazione che non ha.
        """
        volute = frozenset(tags)
        fuori = []
        for c in self.components(plugin=plugin, style=style):
            # i tag possono stare sul componente o sull'innesto: chi cerca non
            # e' tenuto a sapere in anticipo dove l'autore li ha messi
            if volute and not (volute <= c.tags or c.accepts(capability, side, volute)):
                continue
            if capability and not (c.provides_capability(capability)
                                   or c.accepts(capability, side)):
                continue
            if not capability and side and not c.accepts("", side):
                continue
            fuori.append(c)
        return fuori

    def socket_providers(self, capability: str = "", side: str = "",
                         tags: Iterable[str] = ()) -> list[Component]:
        """Chi espone un innesto per questa capability.

        Qui i tag sono quelli **dell'innesto**, non del componente: e' la query
        stretta, quella che serve al resolver quando cerca dove attaccare.
        """
        volute = frozenset(tags)
        return [c for c in self._all(self._components)
                if c.accepts(capability, side, volute)]

    def capabilities(self) -> list[str]:
        """Tutti i nomi di capability conosciuti: dichiarati oppure usati."""
        nomi = set(self._declared)
        for c in self._components.values():
            nomi |= {p.name for p in c.provides}
            nomi |= {m.capability for m in c.mounts if m.capability}
        return sorted(nomi)

    def capability(self, name: str) -> CapabilityInfo:
        """Chi la fornisce, chi la accetta, chi l'ha introdotta."""
        dichiarata = self._declared.get(name, {})
        fornitori = [c.id for c in self._all(self._components)
                     if c.provides_capability(name)]
        innesti = [c.id for c in self._all(self._components) if c.accepts(name)]
        plugin = {i.partition(SEPARATOR)[0] for i in fornitori + innesti}
        plugin |= set(dichiarata.get("plugins", ()))
        return CapabilityInfo(name=name,
                              description=dichiarata.get("description", ""),
                              tags=frozenset(dichiarata.get("tags", ())),
                              providers=tuple(fornitori), mounts=tuple(innesti),
                              plugins=tuple(sorted(plugin)))

    def tags(self) -> list[str]:
        raccolti: set[str] = set()
        for c in self._components.values():
            raccolti |= c.tags
        for info in self._plugins.values():
            raccolti |= info.tags
        return sorted(raccolti)

    # ------------------------------------------------------------- ricerca #
    def search(self, text: str = "", tags: Iterable[str] = (),
               capability: str = "", limit: int = 0) -> list[Component]:
        """Ricerca testuale elementare su id, nome, descrizione e tag.

        Volutamente stupida: nessun NLP, nessun embedding. Serve a dare a un
        planner un modo di guardare il vocabolario, e a un umano un modo di
        trovare un componente di cui ricorda meta' nome. Il punteggio e' il
        numero di parole che compaiono; a pari punteggio decide l'id, cosi'
        l'ordine e' sempre lo stesso.
        """
        volute = frozenset(tags)
        parole = [p for p in str(text).lower().replace("_", " ").split() if p]

        classificati: list[tuple[int, str, Component]] = []
        for c in self.components(tags=volute):
            if capability and not (c.provides_capability(capability)
                                   or c.accepts(capability)):
                continue
            if not parole:
                classificati.append((0, c.id, c))
                continue
            pagliaio = _haystack(c)
            punti = sum(1 for p in parole if p in pagliaio)
            if punti:
                classificati.append((-punti, c.id, c))

        classificati.sort(key=lambda t: (t[0], t[1]))
        fuori = [c for _, _, c in classificati]
        return fuori[:limit] if limit else fuori

    # -------------------------------------------------------- dipendenze #
    def dependencies(self, plugin_id: str) -> tuple[str, ...]:
        info = self._plugins.get(plugin_id)
        return info.dependencies if info else ()

    def missing_dependencies(self) -> dict[str, tuple[str, ...]]:
        return {info.id: tuple(d for d in info.dependencies
                               if d not in self._plugins)
                for info in self.plugins()
                if any(d not in self._plugins for d in info.dependencies)}

    # ------------------------------------------------------------- utilita' #
    def summary(self) -> dict[str, int]:
        return {"plugin": len(self._plugins), "componenti": len(self._components),
                "effetti": len(self._effects), "stili": len(self._styles),
                "trait": len(self._traits), "trait_rules": len(self._trait_rules),
                "structural_traits": len(self._structural_traits),
                "structural_trait_rules": len(self._structural_trait_rules),
                "layout_policies": len(self._layout_policies),
                "archetypes": len(self._archetypes),
                "profiles": len(self._profiles),
                "implementation_bindings": len(self._implementation_bindings),
                "capability": len(self.capabilities())}

    def describe(self) -> str:
        righe = []
        for info in self.plugins():
            righe.append("%s %s" % (info.id, info.version))
            for c in self.components(plugin=info.id):
                righe.append("  %s" % c.describe())
        return "\n".join(righe)

    def __len__(self) -> int:
        return len(self._components)

    def __contains__(self, id: str) -> bool:
        return self.component(id) is not None

    # -------------------------------------------------------------- interno #
    def _all(self, table: dict) -> list:
        """Sempre in ordine di id qualificato: le query non devono ballare."""
        return [table[k] for k in sorted(table)]

    def _lookup(self, table: dict, key: str):
        """Per id qualificato, o per nome nudo se non e' ambiguo."""
        if key in table:
            return table[key]
        if SEPARATOR in key:
            return None
        candidati = [table[k] for k in sorted(table)
                     if k.partition(SEPARATOR)[2] == key]
        return candidati[0] if len(candidati) == 1 else None

    @staticmethod
    def _semantic_lookup(table: dict, aliases: dict[str, set[str]], key: str):
        if key in table:
            return table[key]
        if SEPARATOR in key:
            return None
        ids = aliases.get(key, set())
        if len(ids) == 1:
            return table[next(iter(ids))]
        candidati = [table[k] for k in sorted(table)
                     if k.partition(SEPARATOR)[2] == key]
        return candidati[0] if len(candidati) == 1 else None

    def named(self, name: str) -> list:
        """Tutti quelli che si chiamano cosi', in qualunque plugin."""
        return [self._components[k] for k in sorted(self._components)
                if k.partition(SEPARATOR)[2] == name]


# --------------------------------------------------------------------------- #
# Caricamento dei moduli
# --------------------------------------------------------------------------- #
def _import_file(path: Path, plugin_id: str):
    """Esegue un file Python come modulo isolato.

    Il nome e' univoco a ogni caricamento: due registry che caricano la stessa
    cartella devono ottenere due vocabolari indipendenti, non lo stesso oggetto
    condiviso a loro insaputa.
    """
    global _contatore
    _contatore += 1
    nome = "_3dgen_plugin_%s_%s_%d" % (plugin_id, path.stem, _contatore)
    spec = importlib.util.spec_from_file_location(nome, path)
    if spec is None or spec.loader is None:
        raise ImportError("non caricabile: %s" % path)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nome] = modulo
    try:
        spec.loader.exec_module(modulo)
    except BaseException:
        sys.modules.pop(nome, None)
        raise
    return modulo


def _harvest(modulo) -> list:
    """Raccoglie cio' che il modulo dichiara, senza chiedergli boilerplate.

    Un plugin scrive i suoi `Component` a livello di modulo, da soli o dentro
    una lista, e basta: nessuna funzione `register()` obbligatoria, nessun
    decoratore da ricordare. Meno cerimonia significa meno modi di sbagliare.
    """
    fuori, visti = [], set()

    def aggiungi(valore) -> None:
        if isinstance(valore, (Component, EffectSpec, TraitSpec, TraitRule,
                               StructuralTraitSpec, StructuralTraitRule,
                               LayoutPolicy, StyleProfile, MaterialSpec,
                               ArchetypeSpec, ProfileSpec, ImplementationBinding)):
            if id(valore) not in visti:
                visti.add(id(valore))
                fuori.append(valore)

    for nome, valore in sorted(vars(modulo).items()):
        if nome.startswith("_"):
            continue
        aggiungi(valore)
        if isinstance(valore, (list, tuple, set, frozenset)):
            for elemento in valore:
                aggiungi(elemento)
        elif isinstance(valore, dict):
            for elemento in valore.values():
                aggiungi(elemento)
    return fuori


def _haystack(component: Component) -> str:
    pezzi = [component.id, component.name, component.description,
             " ".join(sorted(component.tags)),
             " ".join(sorted(c.name for c in component.provides)),
             " ".join(sorted(m.capability for m in component.mounts))]
    return " ".join(pezzi).lower().replace("_", " ")


def load(paths: Iterable[str]) -> Registry:
    """Un registry caricato da una o piu' cartelle. La via breve."""
    registry = Registry()
    for percorso in paths:
        registry.load_directory(percorso)
    return registry
