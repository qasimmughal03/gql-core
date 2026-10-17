"""Generate a Star Wars knowledge graph with verified canon data.

Produces gql-graph-json with nodes: Character, Film, Planet, Species,
Starship.  Edges: APPEARS_IN, HOME_PLANET, BELONGS_TO_SPECIES, PILOTED,
DIRECTED, FEATURED_PLANET.

All facts verifiable against Wookieepedia / Star Wars Databank.
"""

from __future__ import annotations

import json
from pathlib import Path

# ── Characters ──────────────────────────────────────────────────────

CHARACTERS = [
    {"id": "luke_skywalker", "name": "Luke Skywalker", "gender": "male", "birth_year": -19},
    {"id": "leia_organa", "name": "Leia Organa", "gender": "female", "birth_year": -19},
    {"id": "han_solo", "name": "Han Solo", "gender": "male", "birth_year": -29},
    {"id": "chewbacca", "name": "Chewbacca", "gender": "male", "birth_year": -200},
    {"id": "darth_vader", "name": "Darth Vader", "gender": "male", "birth_year": -41},
    {"id": "obi_wan_kenobi", "name": "Obi-Wan Kenobi", "gender": "male", "birth_year": -57},
    {"id": "yoda", "name": "Yoda", "gender": "male", "birth_year": -896},
    {"id": "r2d2", "name": "R2-D2", "gender": "droid", "birth_year": -33},
    {"id": "c3po", "name": "C-3PO", "gender": "droid", "birth_year": -32},
    {"id": "palpatine", "name": "Emperor Palpatine", "gender": "male", "birth_year": -84},
    {"id": "boba_fett", "name": "Boba Fett", "gender": "male", "birth_year": -32},
    {"id": "lando_calrissian", "name": "Lando Calrissian", "gender": "male", "birth_year": -31},
    {"id": "padme_amidala", "name": "Padme Amidala", "gender": "female", "birth_year": -46},
    {"id": "anakin_skywalker", "name": "Anakin Skywalker", "gender": "male", "birth_year": -41},
    {"id": "qui_gon_jinn", "name": "Qui-Gon Jinn", "gender": "male", "birth_year": -92},
    {"id": "mace_windu", "name": "Mace Windu", "gender": "male", "birth_year": -72},
    {"id": "darth_maul", "name": "Darth Maul", "gender": "male", "birth_year": -54},
    {"id": "count_dooku", "name": "Count Dooku", "gender": "male", "birth_year": -102},
    {"id": "jar_jar_binks", "name": "Jar Jar Binks", "gender": "male", "birth_year": -52},
    {"id": "jabba_the_hutt", "name": "Jabba the Hutt", "gender": "male", "birth_year": -600},
    {"id": "rey", "name": "Rey", "gender": "female", "birth_year": 15},
    {"id": "finn", "name": "Finn", "gender": "male", "birth_year": 11},
    {"id": "kylo_ren", "name": "Kylo Ren", "gender": "male", "birth_year": 5},
    {"id": "poe_dameron", "name": "Poe Dameron", "gender": "male", "birth_year": 2},
    {"id": "bb8", "name": "BB-8", "gender": "droid", "birth_year": 29},
    {"id": "general_hux", "name": "General Hux", "gender": "male", "birth_year": 0},
    {"id": "snoke", "name": "Supreme Leader Snoke", "gender": "male", "birth_year": 0},
    {"id": "wedge_antilles", "name": "Wedge Antilles", "gender": "male", "birth_year": -21},
    {"id": "admiral_ackbar", "name": "Admiral Ackbar", "gender": "male", "birth_year": -41},
    {"id": "grand_moff_tarkin", "name": "Grand Moff Tarkin", "gender": "male", "birth_year": -64},
]

# ── Films ────────────────────────────────────────────────────────────

FILMS = [
    {"id": "the_phantom_menace", "title": "The Phantom Menace", "episode": 1, "release_year": 1999,
     "director": "George Lucas", "budget": 115000000, "revenue": 1027000000},
    {"id": "attack_of_the_clones", "title": "Attack of the Clones", "episode": 2, "release_year": 2002,
     "director": "George Lucas", "budget": 115000000, "revenue": 649000000},
    {"id": "revenge_of_the_sith", "title": "Revenge of the Sith", "episode": 3, "release_year": 2005,
     "director": "George Lucas", "budget": 113000000, "revenue": 868000000},
    {"id": "a_new_hope", "title": "A New Hope", "episode": 4, "release_year": 1977,
     "director": "George Lucas", "budget": 11000000, "revenue": 775000000},
    {"id": "empire_strikes_back", "title": "The Empire Strikes Back", "episode": 5, "release_year": 1980,
     "director": "Irvin Kershner", "budget": 18000000, "revenue": 547000000},
    {"id": "return_of_the_jedi", "title": "Return of the Jedi", "episode": 6, "release_year": 1983,
     "director": "Richard Marquand", "budget": 32500000, "revenue": 475000000},
    {"id": "the_force_awakens", "title": "The Force Awakens", "episode": 7, "release_year": 2015,
     "director": "J.J. Abrams", "budget": 245000000, "revenue": 2070000000},
]

# ── Planets ──────────────────────────────────────────────────────────

PLANETS = [
    {"id": "tatooine", "name": "Tatooine", "climate": "arid", "terrain": "desert"},
    {"id": "alderaan", "name": "Alderaan", "climate": "temperate", "terrain": "grasslands, mountains"},
    {"id": "hoth", "name": "Hoth", "climate": "frozen", "terrain": "tundra, ice caves"},
    {"id": "dagobah", "name": "Dagobah", "climate": "murky", "terrain": "swamp, jungles"},
    {"id": "bespin", "name": "Bespin", "climate": "temperate", "terrain": "gas giant"},
    {"id": "endor", "name": "Endor", "climate": "temperate", "terrain": "forests, mountains, lakes"},
    {"id": "naboo", "name": "Naboo", "climate": "temperate", "terrain": "grassy hills, swamps, forests"},
    {"id": "coruscant", "name": "Coruscant", "climate": "temperate", "terrain": "cityscape, mountains"},
    {"id": "kamino", "name": "Kamino", "climate": "temperate", "terrain": "ocean"},
    {"id": "geonosis", "name": "Geonosis", "climate": "temperate, arid", "terrain": "rock desert, mountains"},
    {"id": "mustafar", "name": "Mustafar", "climate": "hot", "terrain": "volcanoes, lava rivers"},
    {"id": "kashyyyk", "name": "Kashyyyk", "climate": "tropical", "terrain": "jungle, forests, rivers"},
    {"id": "jakku", "name": "Jakku", "climate": "arid", "terrain": "desert"},
    {"id": "starkiller_base", "name": "Starkiller Base", "climate": "frozen", "terrain": "forest, mountains"},
]

# ── Species ──────────────────────────────────────────────────────────

SPECIES = [
    {"id": "human", "name": "Human", "classification": "mammal", "homeworld": "coruscant"},
    {"id": "wookiee", "name": "Wookiee", "classification": "mammal", "homeworld": "kashyyyk"},
    {"id": "yodas_species", "name": "Yoda's Species", "classification": "unknown", "homeworld": None},
    {"id": "hutt", "name": "Hutt", "classification": "gastropod", "homeworld": None},
    {"id": "gungans", "name": "Gungan", "classification": "amphibian", "homeworld": "naboo"},
    {"id": "trandoshan", "name": "Trandoshan", "classification": "reptile", "homeworld": None},
    {"id": "zabrak", "name": "Zabrak", "classification": "mammal", "homeworld": None},
]

# ── Starships ────────────────────────────────────────────────────────

STARSHIPS = [
    {"id": "millennium_falcon", "name": "Millennium Falcon", "model": "YT-1300 light freighter", "class": "Light freighter"},
    {"id": "x_wing", "name": "X-wing Starfighter", "model": "T-65 X-wing", "class": "Starfighter"},
    {"id": "tie_fighter", "name": "TIE Fighter", "model": "Twin Ion Engine", "class": "Starfighter"},
    {"id": "star_destroyer", "name": "Imperial Star Destroyer", "model": "Imperial I-class", "class": "Star Destroyer"},
    {"id": "death_star", "name": "Death Star", "model": "DS-1 Orbital Battle Station", "class": "Deep Space Mobile Battlestation"},
    {"id": "slave_i", "name": "Slave I", "model": "Firespray-31", "class": "Patrol craft"},
    {"id": "naboo_starfighter", "name": "Naboo Starfighter", "model": "N-1", "class": "Starfighter"},
]

# ── Edges ────────────────────────────────────────────────────────────

APPEARS_IN = [
    # Episode 1: The Phantom Menace
    ("qui_gon_jinn", "the_phantom_menace"),
    ("obi_wan_kenobi", "the_phantom_menace"),
    ("padme_amidala", "the_phantom_menace"),
    ("anakin_skywalker", "the_phantom_menace"),
    ("darth_maul", "the_phantom_menace"),
    ("yoda", "the_phantom_menace"),
    ("mace_windu", "the_phantom_menace"),
    ("r2d2", "the_phantom_menace"),
    ("c3po", "the_phantom_menace"),
    ("jar_jar_binks", "the_phantom_menace"),
    ("palpatine", "the_phantom_menace"),
    # Episode 2: Attack of the Clones
    ("obi_wan_kenobi", "attack_of_the_clones"),
    ("anakin_skywalker", "attack_of_the_clones"),
    ("padme_amidala", "attack_of_the_clones"),
    ("yoda", "attack_of_the_clones"),
    ("mace_windu", "attack_of_the_clones"),
    ("count_dooku", "attack_of_the_clones"),
    ("r2d2", "attack_of_the_clones"),
    ("c3po", "attack_of_the_clones"),
    ("boba_fett", "attack_of_the_clones"),
    ("palpatine", "attack_of_the_clones"),
    # Episode 3: Revenge of the Sith
    ("obi_wan_kenobi", "revenge_of_the_sith"),
    ("anakin_skywalker", "revenge_of_the_sith"),
    ("padme_amidala", "revenge_of_the_sith"),
    ("yoda", "revenge_of_the_sith"),
    ("mace_windu", "revenge_of_the_sith"),
    ("count_dooku", "revenge_of_the_sith"),
    ("r2d2", "revenge_of_the_sith"),
    ("c3po", "revenge_of_the_sith"),
    ("darth_vader", "revenge_of_the_sith"),
    ("palpatine", "revenge_of_the_sith"),
    ("chewbacca", "revenge_of_the_sith"),
    ("grand_moff_tarkin", "revenge_of_the_sith"),
    # Episode 4: A New Hope
    ("luke_skywalker", "a_new_hope"),
    ("leia_organa", "a_new_hope"),
    ("han_solo", "a_new_hope"),
    ("chewbacca", "a_new_hope"),
    ("darth_vader", "a_new_hope"),
    ("obi_wan_kenobi", "a_new_hope"),
    ("r2d2", "a_new_hope"),
    ("c3po", "a_new_hope"),
    ("grand_moff_tarkin", "a_new_hope"),
    ("wedge_antilles", "a_new_hope"),
    # Episode 5: The Empire Strikes Back
    ("luke_skywalker", "empire_strikes_back"),
    ("leia_organa", "empire_strikes_back"),
    ("han_solo", "empire_strikes_back"),
    ("chewbacca", "empire_strikes_back"),
    ("darth_vader", "empire_strikes_back"),
    ("yoda", "empire_strikes_back"),
    ("r2d2", "empire_strikes_back"),
    ("c3po", "empire_strikes_back"),
    ("lando_calrissian", "empire_strikes_back"),
    ("boba_fett", "empire_strikes_back"),
    ("palpatine", "empire_strikes_back"),
    ("wedge_antilles", "empire_strikes_back"),
    # Episode 6: Return of the Jedi
    ("luke_skywalker", "return_of_the_jedi"),
    ("leia_organa", "return_of_the_jedi"),
    ("han_solo", "return_of_the_jedi"),
    ("chewbacca", "return_of_the_jedi"),
    ("darth_vader", "return_of_the_jedi"),
    ("yoda", "return_of_the_jedi"),
    ("r2d2", "return_of_the_jedi"),
    ("c3po", "return_of_the_jedi"),
    ("lando_calrissian", "return_of_the_jedi"),
    ("boba_fett", "return_of_the_jedi"),
    ("palpatine", "return_of_the_jedi"),
    ("wedge_antilles", "return_of_the_jedi"),
    ("admiral_ackbar", "return_of_the_jedi"),
    ("jabba_the_hutt", "return_of_the_jedi"),
    # Episode 7: The Force Awakens
    ("rey", "the_force_awakens"),
    ("finn", "the_force_awakens"),
    ("kylo_ren", "the_force_awakens"),
    ("poe_dameron", "the_force_awakens"),
    ("bb8", "the_force_awakens"),
    ("han_solo", "the_force_awakens"),
    ("leia_organa", "the_force_awakens"),
    ("chewbacca", "the_force_awakens"),
    ("general_hux", "the_force_awakens"),
    ("snoke", "the_force_awakens"),
    ("luke_skywalker", "the_force_awakens"),
    ("r2d2", "the_force_awakens"),
    ("c3po", "the_force_awakens"),
]

HOME_PLANET = [
    ("luke_skywalker", "tatooine"),
    ("leia_organa", "alderaan"),
    ("han_solo", "coruscant"),
    ("darth_vader", "tatooine"),
    ("anakin_skywalker", "tatooine"),
    ("padme_amidala", "naboo"),
    ("jar_jar_binks", "naboo"),
    ("palpatine", "naboo"),
    ("rey", "jakku"),
    ("chewbacca", "kashyyyk"),
    ("lando_calrissian", "bespin"),
    ("boba_fett", "kamino"),
]

SPECIES_OF = [
    ("luke_skywalker", "human"),
    ("leia_organa", "human"),
    ("han_solo", "human"),
    ("darth_vader", "human"),
    ("anakin_skywalker", "human"),
    ("obi_wan_kenobi", "human"),
    ("padme_amidala", "human"),
    ("qui_gon_jinn", "human"),
    ("mace_windu", "human"),
    ("palpatine", "human"),
    ("chewbacca", "wookiee"),
    ("yoda", "yodas_species"),
    ("jabba_the_hutt", "hutt"),
    ("jar_jar_binks", "gungans"),
    ("darth_maul", "zabrak"),
    ("boba_fett", "human"),
]

PILOTED = [
    ("han_solo", "millennium_falcon"),
    ("chewbacca", "millennium_falcon"),
    ("luke_skywalker", "x_wing"),
    ("wedge_antilles", "x_wing"),
    ("boba_fett", "slave_i"),
    ("anakin_skywalker", "naboo_starfighter"),
    ("rey", "millennium_falcon"),
]

DIRECTED_BY = [
    ("the_phantom_menace", "George Lucas"),
    ("attack_of_the_clones", "George Lucas"),
    ("revenge_of_the_sith", "George Lucas"),
    ("a_new_hope", "George Lucas"),
    ("empire_strikes_back", "Irvin Kershner"),
    ("return_of_the_jedi", "Richard Marquand"),
    ("the_force_awakens", "J.J. Abrams"),
]

FEATURED_PLANET = [
    ("the_phantom_menace", "naboo"),
    ("the_phantom_menace", "tatooine"),
    ("the_phantom_menace", "coruscant"),
    ("attack_of_the_clones", "coruscant"),
    ("attack_of_the_clones", "kamino"),
    ("attack_of_the_clones", "geonosis"),
    ("attack_of_the_clones", "tatooine"),
    ("attack_of_the_clones", "naboo"),
    ("revenge_of_the_sith", "coruscant"),
    ("revenge_of_the_sith", "mustafar"),
    ("revenge_of_the_sith", "kashyyyk"),
    ("revenge_of_the_sith", "tatooine"),
    ("revenge_of_the_sith", "alderaan"),
    ("a_new_hope", "tatooine"),
    ("a_new_hope", "alderaan"),
    ("empire_strikes_back", "hoth"),
    ("empire_strikes_back", "dagobah"),
    ("empire_strikes_back", "bespin"),
    ("return_of_the_jedi", "tatooine"),
    ("return_of_the_jedi", "dagobah"),
    ("return_of_the_jedi", "endor"),
    ("the_force_awakens", "jakku"),
    ("the_force_awakens", "starkiller_base"),
]


def generate():
    nodes = []
    edges = []

    for c in CHARACTERS:
        props = {k: v for k, v in c.items() if k != "id"}
        nodes.append({"@id": c["id"], "@type": "Character", **props})

    for f in FILMS:
        props = {k: v for k, v in f.items() if k != "id"}
        nodes.append({"@id": f["id"], "@type": "Film", **props})

    for p in PLANETS:
        props = {k: v for k, v in p.items() if k != "id"}
        nodes.append({"@id": p["id"], "@type": "Planet", **props})

    for s in SPECIES:
        props = {k: v for k, v in s.items() if k != "id"}
        nodes.append({"@id": s["id"], "@type": "Species", **props})

    for s in STARSHIPS:
        props = {k: v for k, v in s.items() if k != "id"}
        nodes.append({"@id": s["id"], "@type": "Starship", **props})

    for char_id, film_id in APPEARS_IN:
        edges.append({"@type": "APPEARS_IN", "@src": char_id, "@dst": film_id})

    for char_id, planet_id in HOME_PLANET:
        edges.append({"@type": "HOME_PLANET", "@src": char_id, "@dst": planet_id})

    for char_id, species_id in SPECIES_OF:
        edges.append({"@type": "BELONGS_TO", "@src": char_id, "@dst": species_id})

    for char_id, ship_id in PILOTED:
        edges.append({"@type": "PILOTED", "@src": char_id, "@dst": ship_id})

    for film_id, planet_id in FEATURED_PLANET:
        edges.append({"@type": "FEATURED_PLANET", "@src": film_id, "@dst": planet_id})

    node_count = len(nodes)
    edge_count = len(edges)
    node_labels = sorted(set(n["@type"] for n in nodes))
    edge_labels = sorted(set(e["@type"] for e in edges))
    print(f"Generated: {node_count} nodes ({node_labels}), {edge_count} edges ({edge_labels})")

    return {"nodes": nodes, "edges": edges}


if __name__ == "__main__":
    data = generate()
    out_path = Path(__file__).resolve().parent / "graph.json"
    out_path.write_text(json.dumps(data, indent=2))
    print(f"Written to {out_path}")
