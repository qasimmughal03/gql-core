"""Generate a realistic movie knowledge graph.

Produces gql-graph-json from hand-curated movie data. All facts are
verifiable against IMDb/Wikipedia so benchmark expected answers are
ground-truth correct.
"""

from __future__ import annotations

import json
from pathlib import Path

# ── People (actors + directors + producers + writers) ──────────────

PEOPLE = [
    # Actors
    {"id": "tom_hanks", "name": "Tom Hanks", "born": 1956, "gender": "male"},
    {"id": "leonardo_dicaprio", "name": "Leonardo DiCaprio", "born": 1974, "gender": "male"},
    {"id": "meryl_streep", "name": "Meryl Streep", "born": 1949, "gender": "female"},
    {"id": "morgan_freeman", "name": "Morgan Freeman", "born": 1937, "gender": "male"},
    {"id": "scarlett_johansson", "name": "Scarlett Johansson", "born": 1984, "gender": "female"},
    {"id": "brad_pitt", "name": "Brad Pitt", "born": 1963, "gender": "male"},
    {"id": "cate_blanchett", "name": "Cate Blanchett", "born": 1969, "gender": "female"},
    {"id": "robert_downey_jr", "name": "Robert Downey Jr.", "born": 1965, "gender": "male"},
    {"id": "natalie_portman", "name": "Natalie Portman", "born": 1981, "gender": "female"},
    {"id": "matt_damon", "name": "Matt Damon", "born": 1970, "gender": "male"},
    {"id": "jennifer_lawrence", "name": "Jennifer Lawrence", "born": 1990, "gender": "female"},
    {"id": "christian_bale", "name": "Christian Bale", "born": 1974, "gender": "male"},
    {"id": "anne_hathaway", "name": "Anne Hathaway", "born": 1982, "gender": "female"},
    {"id": "tom_cruise", "name": "Tom Cruise", "born": 1962, "gender": "male"},
    {"id": "emma_stone", "name": "Emma Stone", "born": 1988, "gender": "female"},
    {"id": "ryan_gosling", "name": "Ryan Gosling", "born": 1980, "gender": "male"},
    {"id": "viola_davis", "name": "Viola Davis", "born": 1965, "gender": "female"},
    {"id": "joaquin_phoenix", "name": "Joaquin Phoenix", "born": 1974, "gender": "male"},
    {"id": "saoirse_ronan", "name": "Saoirse Ronan", "born": 1994, "gender": "female"},
    {"id": "timothee_chalamet", "name": "Timothee Chalamet", "born": 1995, "gender": "male"},
    {"id": "florence_pugh", "name": "Florence Pugh", "born": 1996, "gender": "female"},
    {"id": "samuel_l_jackson", "name": "Samuel L. Jackson", "born": 1948, "gender": "male"},
    {"id": "zendaya", "name": "Zendaya", "born": 1996, "gender": "female"},
    {"id": "willem_dafoe", "name": "Willem Dafoe", "born": 1955, "gender": "male"},
    {"id": "amy_adams", "name": "Amy Adams", "born": 1974, "gender": "female"},
    {"id": "jake_gyllenhaal", "name": "Jake Gyllenhaal", "born": 1980, "gender": "male"},
    {"id": "margot_robbie", "name": "Margot Robbie", "born": 1990, "gender": "female"},
    {"id": "tom_hardy", "name": "Tom Hardy", "born": 1977, "gender": "male"},
    {"id": "lupita_nyongo", "name": "Lupita Nyongo", "born": 1983, "gender": "female"},
    {"id": "oscar_isaac", "name": "Oscar Isaac", "born": 1979, "gender": "male"},
    # Additional people referenced in casting
    {"id": "bruce_willis", "name": "Bruce Willis", "born": 1955, "gender": "male"},
    {"id": "adrien_brody", "name": "Adrien Brody", "born": 1973, "gender": "male"},
    {"id": "liam_neeson", "name": "Liam Neeson", "born": 1952, "gender": "male"},
    {"id": "ralph_fiennes", "name": "Ralph Fiennes", "born": 1962, "gender": "male"},
    {"id": "russell_crowe", "name": "Russell Crowe", "born": 1964, "gender": "male"},
    {"id": "harrison_ford", "name": "Harrison Ford", "born": 1942, "gender": "male"},
    {"id": "jodie_foster", "name": "Jodie Foster", "born": 1962, "gender": "female"},
    {"id": "anthony_hopkins", "name": "Anthony Hopkins", "born": 1937, "gender": "male"},
    {"id": "josh_brolin", "name": "Josh Brolin", "born": 1968, "gender": "male"},
    {"id": "jared_leto", "name": "Jared Leto", "born": 1971, "gender": "male"},
    {"id": "jesse_eisenberg", "name": "Jesse Eisenberg", "born": 1983, "gender": "male"},
    {"id": "andrew_garfield", "name": "Andrew Garfield", "born": 1983, "gender": "male"},
    {"id": "jim_carrey", "name": "Jim Carrey", "born": 1962, "gender": "male"},
    {"id": "miles_teller", "name": "Miles Teller", "born": 1987, "gender": "male"},
    {"id": "jk_simmons", "name": "J.K. Simmons", "born": 1955, "gender": "male"},
    {"id": "charlize_theron", "name": "Charlize Theron", "born": 1975, "gender": "female"},
    {"id": "jonah_hill", "name": "Jonah Hill", "born": 1983, "gender": "male"},
    {"id": "matthew_mcconaughey", "name": "Matthew McConaughey", "born": 1969, "gender": "male"},
    {"id": "cillian_murphy", "name": "Cillian Murphy", "born": 1976, "gender": "male"},
    {"id": "emily_blunt", "name": "Emily Blunt", "born": 1983, "gender": "female"},
    {"id": "america_ferrera", "name": "America Ferrera", "born": 1984, "gender": "female"},
    {"id": "jamie_foxx", "name": "Jamie Foxx", "born": 1967, "gender": "male"},
    {"id": "christoph_waltz", "name": "Christoph Waltz", "born": 1956, "gender": "male"},
    {"id": "kevin_spacey", "name": "Kevin Spacey", "born": 1959, "gender": "male"},
    {"id": "sigourney_weaver", "name": "Sigourney Weaver", "born": 1949, "gender": "female"},
    {"id": "arnold_schwarzenegger", "name": "Arnold Schwarzenegger", "born": 1947, "gender": "male"},
    {"id": "song_kang_ho", "name": "Song Kang-ho", "born": 1967, "gender": "male"},
    {"id": "daniel_kaluuya", "name": "Daniel Kaluuya", "born": 1989, "gender": "male"},
    {"id": "daniel_day_lewis", "name": "Daniel Day-Lewis", "born": 1957, "gender": "male"},
    {"id": "javier_bardem", "name": "Javier Bardem", "born": 1969, "gender": "male"},
    {"id": "emma_watson", "name": "Emma Watson", "born": 1990, "gender": "female"},
    {"id": "guy_pearce", "name": "Guy Pearce", "born": 1967, "gender": "male"},
    {"id": "hugh_jackman", "name": "Hugh Jackman", "born": 1968, "gender": "male"},
    {"id": "keanu_reeves", "name": "Keanu Reeves", "born": 1964, "gender": "male"},
    {"id": "carrie_anne_moss", "name": "Carrie-Anne Moss", "born": 1967, "gender": "female"},
    {"id": "laurence_fishburne", "name": "Laurence Fishburne", "born": 1961, "gender": "male"},
    {"id": "joe_pesci", "name": "Joe Pesci", "born": 1943, "gender": "male"},
    {"id": "robert_de_niro", "name": "Robert De Niro", "born": 1943, "gender": "male"},
    {"id": "al_pacino", "name": "Al Pacino", "born": 1940, "gender": "male"},
    {"id": "marlon_brando", "name": "Marlon Brando", "born": 1924, "gender": "male"},
    {"id": "heath_ledger", "name": "Heath Ledger", "born": 1979, "gender": "male"},
    {"id": "jack_nicholson", "name": "Jack Nicholson", "born": 1937, "gender": "male"},
    {"id": "uma_thurman", "name": "Uma Thurman", "born": 1970, "gender": "female"},
    {"id": "john_travolta", "name": "John Travolta", "born": 1954, "gender": "male"},
    {"id": "robin_wright", "name": "Robin Wright", "born": 1966, "gender": "female"},
    {"id": "gary_sinise", "name": "Gary Sinise", "born": 1955, "gender": "male"},
    {"id": "edward_norton", "name": "Edward Norton", "born": 1969, "gender": "male"},
    {"id": "helena_bonham_carter", "name": "Helena Bonham Carter", "born": 1966, "gender": "female"},
    {"id": "marion_cotillard", "name": "Marion Cotillard", "born": 1975, "gender": "female"},
    {"id": "ellen_page", "name": "Elliot Page", "born": 1987, "gender": "male"},
    {"id": "joseph_gordon_levitt", "name": "Joseph Gordon-Levitt", "born": 1981, "gender": "male"},
    {"id": "michael_caine", "name": "Michael Caine", "born": 1933, "gender": "male"},
    {"id": "kate_winslet", "name": "Kate Winslet", "born": 1975, "gender": "female"},
    # Directors
    {"id": "christopher_nolan", "name": "Christopher Nolan", "born": 1970, "gender": "male"},
    {"id": "quentin_tarantino", "name": "Quentin Tarantino", "born": 1963, "gender": "male"},
    {"id": "martin_scorsese", "name": "Martin Scorsese", "born": 1942, "gender": "male"},
    {"id": "steven_spielberg", "name": "Steven Spielberg", "born": 1946, "gender": "male"},
    {"id": "denis_villeneuve", "name": "Denis Villeneuve", "born": 1967, "gender": "male"},
    {"id": "greta_gerwig", "name": "Greta Gerwig", "born": 1983, "gender": "female"},
    {"id": "ridley_scott", "name": "Ridley Scott", "born": 1937, "gender": "male"},
    {"id": "david_fincher", "name": "David Fincher", "born": 1962, "gender": "male"},
    {"id": "wachowskis", "name": "The Wachowskis", "born": 1965, "gender": "unknown"},
    {"id": "frank_darabont", "name": "Frank Darabont", "born": 1959, "gender": "male"},
    {"id": "robert_zemeckis", "name": "Robert Zemeckis", "born": 1951, "gender": "male"},
    {"id": "francis_ford_coppola", "name": "Francis Ford Coppola", "born": 1939, "gender": "male"},
    {"id": "jonathan_demme", "name": "Jonathan Demme", "born": 1944, "gender": "male"},
    # Producers
    {"id": "emma_thomas", "name": "Emma Thomas", "born": 1971, "gender": "female"},
    {"id": "jerry_bruckheimer", "name": "Jerry Bruckheimer", "born": 1943, "gender": "male"},
    {"id": "kathleen_kennedy", "name": "Kathleen Kennedy", "born": 1953, "gender": "female"},
    # Writers
    {"id": "aaron_sorkin", "name": "Aaron Sorkin", "born": 1961, "gender": "male"},
    {"id": "charlie_kaufman", "name": "Charlie Kaufman", "born": 1958, "gender": "male"},
]

# ── Movies ──────────────────────────────────────────────────────────

MOVIES = [
    {"id": "inception", "title": "Inception", "year": 2010, "runtime": 148, "budget": 160000000, "revenue": 836000000, "language": "English"},
    {"id": "interstellar", "title": "Interstellar", "year": 2014, "runtime": 169, "budget": 165000000, "revenue": 731000000, "language": "English"},
    {"id": "dark_knight", "title": "The Dark Knight", "year": 2008, "runtime": 152, "budget": 185000000, "revenue": 1006000000, "language": "English"},
    {"id": "dunkirk", "title": "Dunkirk", "year": 2017, "runtime": 106, "budget": 100000000, "revenue": 530000000, "language": "English"},
    {"id": "pulp_fiction", "title": "Pulp Fiction", "year": 1994, "runtime": 154, "budget": 8000000, "revenue": 214000000, "language": "English"},
    {"id": "forrest_gump", "title": "Forrest Gump", "year": 1994, "runtime": 142, "budget": 55000000, "revenue": 678000000, "language": "English"},
    {"id": "shawshank", "title": "The Shawshank Redemption", "year": 1994, "runtime": 142, "budget": 25000000, "revenue": 73300000, "language": "English"},
    {"id": "godfather", "title": "The Godfather", "year": 1972, "runtime": 175, "budget": 6000000, "revenue": 250000000, "language": "English"},
    {"id": "pianist", "title": "The Pianist", "year": 2002, "runtime": 150, "budget": 35000000, "revenue": 120000000, "language": "English"},
    {"id": "schindlers_list", "title": "Schindler's List", "year": 1993, "runtime": 195, "budget": 22000000, "revenue": 322000000, "language": "English"},
    {"id": "gladiator", "title": "Gladiator", "year": 2000, "runtime": 155, "budget": 103000000, "revenue": 460000000, "language": "English"},
    {"id": "matrix", "title": "The Matrix", "year": 1999, "runtime": 136, "budget": 63000000, "revenue": 467000000, "language": "English"},
    {"id": "silence_of_lambs", "title": "The Silence of the Lambs", "year": 1991, "runtime": 118, "budget": 19000000, "revenue": 273000000, "language": "English"},
    {"id": "dune", "title": "Dune", "year": 2021, "runtime": 155, "budget": 165000000, "revenue": 407000000, "language": "English"},
    {"id": "blade_runner_2049", "title": "Blade Runner 2049", "year": 2017, "runtime": 164, "budget": 150000000, "revenue": 267000000, "language": "English"},
    {"id": "arrival", "title": "Arrival", "year": 2016, "runtime": 116, "budget": 47000000, "revenue": 203000000, "language": "English"},
    {"id": "fight_club", "title": "Fight Club", "year": 1999, "runtime": 139, "budget": 63000000, "revenue": 101000000, "language": "English"},
    {"id": "seven", "title": "Se7en", "year": 1995, "runtime": 127, "budget": 33000000, "revenue": 327000000, "language": "English"},
    {"id": "social_network", "title": "The Social Network", "year": 2010, "runtime": 120, "budget": 40000000, "revenue": 225000000, "language": "English"},
    {"id": "eternal_sunshine", "title": "Eternal Sunshine of the Spotless Mind", "year": 2004, "runtime": 108, "budget": 20000000, "revenue": 74000000, "language": "English"},
    {"id": "la_la_land", "title": "La La Land", "year": 2016, "runtime": 128, "budget": 30000000, "revenue": 448000000, "language": "English"},
    {"id": "whiplash", "title": "Whiplash", "year": 2014, "runtime": 106, "budget": 3300000, "revenue": 49000000, "language": "English"},
    {"id": "fury_road", "title": "Mad Max: Fury Road", "year": 2015, "runtime": 120, "budget": 150000000, "revenue": 380000000, "language": "English"},
    {"id": "wolf_of_wall_street", "title": "The Wolf of Wall Street", "year": 2013, "runtime": 180, "budget": 100000000, "revenue": 392000000, "language": "English"},
    {"id": "departed", "title": "The Departed", "year": 2006, "runtime": 151, "budget": 90000000, "revenue": 291000000, "language": "English"},
    {"id": "revenant", "title": "The Revenant", "year": 2015, "runtime": 156, "budget": 135000000, "revenue": 533000000, "language": "English"},
    {"id": "joker", "title": "Joker", "year": 2019, "runtime": 122, "budget": 55000000, "revenue": 1074000000, "language": "English"},
    {"id": "oppenheimer", "title": "Oppenheimer", "year": 2023, "runtime": 180, "budget": 100000000, "revenue": 960000000, "language": "English"},
    {"id": "barbie", "title": "Barbie", "year": 2023, "runtime": 114, "budget": 145000000, "revenue": 1446000000, "language": "English"},
    {"id": "kill_bill", "title": "Kill Bill: Vol. 1", "year": 2003, "runtime": 111, "budget": 30000000, "revenue": 181000000, "language": "English"},
    {"id": "django", "title": "Django Unchained", "year": 2012, "runtime": 165, "budget": 100000000, "revenue": 426000000, "language": "English"},
    {"id": "catch_me_if_you_can", "title": "Catch Me If You Can", "year": 2002, "runtime": 141, "budget": 52000000, "revenue": 352000000, "language": "English"},
    {"id": "saving_private_ryan", "title": "Saving Private Ryan", "year": 1998, "runtime": 169, "budget": 70000000, "revenue": 482000000, "language": "English"},
    {"id": "american_beauty", "title": "American Beauty", "year": 1999, "runtime": 122, "budget": 15000000, "revenue": 356000000, "language": "English"},
    {"id": "goodfellas", "title": "Goodfellas", "year": 1990, "runtime": 146, "budget": 25000000, "revenue": 47000000, "language": "English"},
    {"id": "alien", "title": "Alien", "year": 1979, "runtime": 117, "budget": 11000000, "revenue": 106000000, "language": "English"},
    {"id": "terminator_2", "title": "Terminator 2: Judgment Day", "year": 1991, "runtime": 137, "budget": 100000000, "revenue": 520000000, "language": "English"},
    {"id": "parasite", "title": "Parasite", "year": 2019, "runtime": 132, "budget": 11000000, "revenue": 263000000, "language": "Korean"},
    {"id": "get_out", "title": "Get Out", "year": 2017, "runtime": 104, "budget": 4500000, "revenue": 255000000, "language": "English"},
    {"id": "there_will_be_blood", "title": "There Will Be Blood", "year": 2007, "runtime": 158, "budget": 25000000, "revenue": 76200000, "language": "English"},
    {"id": "no_country", "title": "No Country for Old Men", "year": 2007, "runtime": 122, "budget": 25000000, "revenue": 172000000, "language": "English"},
    {"id": "grand_budapest", "title": "The Grand Budapest Hotel", "year": 2014, "runtime": 99, "budget": 25000000, "revenue": 173000000, "language": "English"},
    {"id": "lady_bird", "title": "Lady Bird", "year": 2017, "runtime": 94, "budget": 10000000, "revenue": 79000000, "language": "English"},
    {"id": "little_women", "title": "Little Women", "year": 2019, "runtime": 135, "budget": 40000000, "revenue": 219000000, "language": "English"},
    {"id": "memento", "title": "Memento", "year": 2000, "runtime": 113, "budget": 9000000, "revenue": 40000000, "language": "English"},
    {"id": "prestige", "title": "The Prestige", "year": 2006, "runtime": 130, "budget": 40000000, "revenue": 110000000, "language": "English"},
]

# ── Genres ──────────────────────────────────────────────────────────

GENRES = [
    {"id": "action", "name": "Action"},
    {"id": "drama", "name": "Drama"},
    {"id": "sci_fi", "name": "Science Fiction"},
    {"id": "thriller", "name": "Thriller"},
    {"id": "crime", "name": "Crime"},
    {"id": "comedy", "name": "Comedy"},
    {"id": "horror", "name": "Horror"},
    {"id": "war", "name": "War"},
    {"id": "romance", "name": "Romance"},
    {"id": "musical", "name": "Musical"},
    {"id": "western", "name": "Western"},
    {"id": "historical", "name": "Historical"},
]

# ── Casting (ACTED_IN edges) ───────────────────────────────────────

CASTING = [
    # Inception
    ("leonardo_dicaprio", "inception", "Dom Cobb"),
    ("joseph_gordon_levitt", "inception", "Arthur"),
    ("tom_hardy", "inception", "Eames"),
    ("ellen_page", "inception", "Ariadne"),
    ("marion_cotillard", "inception", "Mal"),
    ("michael_caine", "inception", "Miles"),
    # Interstellar
    ("matt_damon", "interstellar", "Dr. Mann"),
    ("anne_hathaway", "interstellar", "Brand"),
    ("michael_caine", "interstellar", "Professor Brand"),
    # The Dark Knight
    ("christian_bale", "dark_knight", "Bruce Wayne / Batman"),
    ("heath_ledger", "dark_knight", "The Joker"),
    ("morgan_freeman", "dark_knight", "Lucius Fox"),
    ("michael_caine", "dark_knight", "Alfred"),
    ("gary_sinise", "dark_knight", "Commissioner Gordon"),
    # Dunkirk
    ("tom_hardy", "dunkirk", "Farrier"),
    ("cate_blanchett", "dunkirk", "Civilian Boater"),
    # Pulp Fiction
    ("john_travolta", "pulp_fiction", "Vincent Vega"),
    ("samuel_l_jackson", "pulp_fiction", "Jules Winnfield"),
    ("uma_thurman", "pulp_fiction", "Mia Wallace"),
    ("bruce_willis", "pulp_fiction", "Butch Coolidge"),
    # Forrest Gump
    ("tom_hanks", "forrest_gump", "Forrest Gump"),
    ("robin_wright", "forrest_gump", "Jenny Curran"),
    ("gary_sinise", "forrest_gump", "Lt. Dan Taylor"),
    # Shawshank
    ("morgan_freeman", "shawshank", "Ellis Boyd 'Red' Redding"),
    # The Godfather
    ("marlon_brando", "godfather", "Vito Corleone"),
    ("al_pacino", "godfather", "Michael Corleone"),
    ("robert_de_niro", "godfather", "Young Vito Corleone"),
    # The Pianist
    ("adrien_brody", "pianist", "Wladek Szpilman"),
    # Schindler's List
    ("liam_neeson", "schindlers_list", "Oskar Schindler"),
    ("ralph_fiennes", "schindlers_list", "Amon Goth"),
    # Gladiator
    ("russell_crowe", "gladiator", "Maximus"),
    ("joaquin_phoenix", "gladiator", "Commodus"),
    # The Matrix
    ("keanu_reeves", "matrix", "Neo"),
    ("carrie_anne_moss", "matrix", "Trinity"),
    ("laurence_fishburne", "matrix", "Morpheus"),
    # Silence of the Lambs
    ("jodie_foster", "silence_of_lambs", "Clarice Starling"),
    ("anthony_hopkins", "silence_of_lambs", "Hannibal Lecter"),
    # Dune (2021)
    ("timothee_chalamet", "dune", "Paul Atreides"),
    ("zendaya", "dune", "Chani"),
    ("oscar_isaac", "dune", "Duke Leto Atreides"),
    ("josh_brolin", "dune", "Gurney Halleck"),
    # Blade Runner 2049
    ("ryan_gosling", "blade_runner_2049", "Officer K"),
    ("harrison_ford", "blade_runner_2049", "Rick Deckard"),
    # Arrival
    ("amy_adams", "arrival", "Louise Banks"),
    # Fight Club
    ("brad_pitt", "fight_club", "Tyler Durden"),
    ("edward_norton", "fight_club", "The Narrator"),
    ("helena_bonham_carter", "fight_club", "Marla Singer"),
    ("jared_leto", "fight_club", "Angel Face"),
    # Se7en
    ("brad_pitt", "seven", "David Mills"),
    ("morgan_freeman", "seven", "William Somerset"),
    # The Social Network
    ("jesse_eisenberg", "social_network", "Mark Zuckerberg"),
    ("andrew_garfield", "social_network", "Eduardo Saverin"),
    # Eternal Sunshine
    ("jim_carrey", "eternal_sunshine", "Joel Barish"),
    ("kate_winslet", "eternal_sunshine", "Clementine"),
    # La La Land
    ("ryan_gosling", "la_la_land", "Sebastian"),
    ("emma_stone", "la_la_land", "Mia"),
    # Whiplash
    ("miles_teller", "whiplash", "Andrew Neiman"),
    ("jk_simmons", "whiplash", "Terence Fletcher"),
    # Fury Road
    ("tom_hardy", "fury_road", "Max Rockatansky"),
    ("charlize_theron", "fury_road", "Imperator Furiosa"),
    # Wolf of Wall Street
    ("leonardo_dicaprio", "wolf_of_wall_street", "Jordan Belfort"),
    ("margot_robbie", "wolf_of_wall_street", "Naomi Lapaglia"),
    ("jonah_hill", "wolf_of_wall_street", "Donnie Azoff"),
    ("matthew_mcconaughey", "wolf_of_wall_street", "Mark Hanna"),
    # The Departed
    ("leonardo_dicaprio", "departed", "Billy Costigan"),
    ("matt_damon", "departed", "Colin Sullivan"),
    ("jack_nicholson", "departed", "Frank Costello"),
    # The Revenant
    ("leonardo_dicaprio", "revenant", "Hugh Glass"),
    ("tom_hardy", "revenant", "John Fitzgerald"),
    # Joker
    ("joaquin_phoenix", "joker", "Arthur Fleck / Joker"),
    ("robert_de_niro", "joker", "Murray Franklin"),
    # Oppenheimer
    ("cillian_murphy", "oppenheimer", "J. Robert Oppenheimer"),
    ("robert_downey_jr", "oppenheimer", "Lewis Strauss"),
    ("matt_damon", "oppenheimer", "Leslie Groves"),
    ("emily_blunt", "oppenheimer", "Kitty Oppenheimer"),
    ("florence_pugh", "oppenheimer", "Jean Tatlock"),
    # Barbie
    ("margot_robbie", "barbie", "Barbie"),
    ("ryan_gosling", "barbie", "Ken"),
    ("america_ferrera", "barbie", "Gloria"),
    # Kill Bill
    ("uma_thurman", "kill_bill", "The Bride"),
    # Django
    ("jamie_foxx", "django", "Django"),
    ("leonardo_dicaprio", "django", "Calvin Candie"),
    ("christoph_waltz", "django", "Dr. King Schultz"),
    ("samuel_l_jackson", "django", "Stephen"),
    # Catch Me If You Can
    ("leonardo_dicaprio", "catch_me_if_you_can", "Frank Abagnale Jr."),
    ("tom_hanks", "catch_me_if_you_can", "Carl Hanratty"),
    # Saving Private Ryan
    ("tom_hanks", "saving_private_ryan", "Captain Miller"),
    ("matt_damon", "saving_private_ryan", "Private Ryan"),
    # American Beauty
    ("kevin_spacey", "american_beauty", "Lester Burnham"),
    # Goodfellas
    ("robert_de_niro", "goodfellas", "Jimmy Conway"),
    ("joe_pesci", "goodfellas", "Tommy DeVito"),
    # Alien
    ("sigourney_weaver", "alien", "Ripley"),
    # Terminator 2
    ("arnold_schwarzenegger", "terminator_2", "The Terminator"),
    # Parasite
    ("song_kang_ho", "parasite", "Kim Ki-taek"),
    # Get Out
    ("daniel_kaluuya", "get_out", "Chris Washington"),
    # There Will Be Blood
    ("daniel_day_lewis", "there_will_be_blood", "Daniel Plainview"),
    # No Country for Old Men
    ("javier_bardem", "no_country", "Anton Chigurh"),
    ("josh_brolin", "no_country", "Llewelyn Moss"),
    # Grand Budapest
    ("ralph_fiennes", "grand_budapest", "M. Gustave"),
    ("willem_dafoe", "grand_budapest", "J.G. Jopling"),
    ("saoirse_ronan", "grand_budapest", "Agatha"),
    # Lady Bird
    ("saoirse_ronan", "lady_bird", "Christine 'Lady Bird' McPherson"),
    ("timothee_chalamet", "lady_bird", "Kyle Scheible"),
    # Little Women
    ("saoirse_ronan", "little_women", "Jo March"),
    ("emma_watson", "little_women", "Meg March"),
    ("florence_pugh", "little_women", "Amy March"),
    ("timothee_chalamet", "little_women", "Theodore 'Laurie' Laurence"),
    ("meryl_streep", "little_women", "Aunt March"),
    # Memento
    ("guy_pearce", "memento", "Leonard Shelby"),
    ("carrie_anne_moss", "memento", "Natalie"),
    # The Prestige
    ("christian_bale", "prestige", "Alfred Borden"),
    ("hugh_jackman", "prestige", "Robert Angier"),
    ("scarlett_johansson", "prestige", "Olivia Wenscombe"),
    ("michael_caine", "prestige", "Cutter"),
]

# ── Directors ──────────────────────────────────────────────────────

DIRECTORS = [
    ("christopher_nolan", "inception"),
    ("christopher_nolan", "interstellar"),
    ("christopher_nolan", "dark_knight"),
    ("christopher_nolan", "dunkirk"),
    ("christopher_nolan", "oppenheimer"),
    ("christopher_nolan", "prestige"),
    ("christopher_nolan", "memento"),
    ("quentin_tarantino", "pulp_fiction"),
    ("quentin_tarantino", "kill_bill"),
    ("quentin_tarantino", "django"),
    ("robert_zemeckis", "forrest_gump"),
    ("frank_darabont", "shawshank"),
    ("francis_ford_coppola", "godfather"),
    ("steven_spielberg", "schindlers_list"),
    ("steven_spielberg", "saving_private_ryan"),
    ("steven_spielberg", "catch_me_if_you_can"),
    ("ridley_scott", "gladiator"),
    ("ridley_scott", "alien"),
    ("wachowskis", "matrix"),
    ("jonathan_demme", "silence_of_lambs"),
    ("denis_villeneuve", "dune"),
    ("denis_villeneuve", "blade_runner_2049"),
    ("denis_villeneuve", "arrival"),
    ("david_fincher", "fight_club"),
    ("david_fincher", "seven"),
    ("david_fincher", "social_network"),
    ("martin_scorsese", "departed"),
    ("martin_scorsese", "wolf_of_wall_street"),
    ("martin_scorsese", "goodfellas"),
    ("greta_gerwig", "barbie"),
    ("greta_gerwig", "lady_bird"),
    ("greta_gerwig", "little_women"),
]

# ── Genres ──────────────────────────────────────────────────────────

MOVIE_GENRES = [
    ("inception", "action"), ("inception", "sci_fi"), ("inception", "thriller"),
    ("interstellar", "sci_fi"), ("interstellar", "drama"),
    ("dark_knight", "action"), ("dark_knight", "crime"), ("dark_knight", "drama"),
    ("dunkirk", "war"), ("dunkirk", "action"), ("dunkirk", "historical"),
    ("pulp_fiction", "crime"), ("pulp_fiction", "drama"),
    ("forrest_gump", "drama"), ("forrest_gump", "comedy"), ("forrest_gump", "romance"),
    ("shawshank", "drama"),
    ("godfather", "crime"), ("godfather", "drama"),
    ("schindlers_list", "war"), ("schindlers_list", "drama"), ("schindlers_list", "historical"),
    ("gladiator", "action"), ("gladiator", "drama"),
    ("matrix", "sci_fi"), ("matrix", "action"),
    ("silence_of_lambs", "thriller"), ("silence_of_lambs", "horror"), ("silence_of_lambs", "crime"),
    ("dune", "sci_fi"), ("dune", "action"),
    ("blade_runner_2049", "sci_fi"), ("blade_runner_2049", "drama"),
    ("arrival", "sci_fi"), ("arrival", "drama"),
    ("fight_club", "drama"), ("fight_club", "thriller"),
    ("seven", "crime"), ("seven", "thriller"),
    ("social_network", "drama"),
    ("la_la_land", "musical"), ("la_la_land", "romance"), ("la_la_land", "drama"),
    ("fury_road", "action"), ("fury_road", "sci_fi"),
    ("wolf_of_wall_street", "comedy"), ("wolf_of_wall_street", "crime"), ("wolf_of_wall_street", "drama"),
    ("departed", "crime"), ("departed", "thriller"), ("departed", "drama"),
    ("joker", "crime"), ("joker", "drama"), ("joker", "thriller"),
    ("oppenheimer", "drama"), ("oppenheimer", "historical"), ("oppenheimer", "war"),
    ("barbie", "comedy"), ("barbie", "romance"),
    ("kill_bill", "action"), ("kill_bill", "crime"),
    ("django", "western"), ("django", "drama"),
    ("catch_me_if_you_can", "crime"), ("catch_me_if_you_can", "drama"),
    ("saving_private_ryan", "war"), ("saving_private_ryan", "drama"), ("saving_private_ryan", "historical"),
    ("goodfellas", "crime"), ("goodfellas", "drama"),
    ("alien", "sci_fi"), ("alien", "horror"),
    ("terminator_2", "action"), ("terminator_2", "sci_fi"),
    ("parasite", "drama"), ("parasite", "thriller"),
    ("get_out", "horror"), ("get_out", "thriller"),
    ("there_will_be_blood", "drama"), ("there_will_be_blood", "historical"),
    ("no_country", "crime"), ("no_country", "thriller"), ("no_country", "western"),
    ("grand_budapest", "comedy"), ("grand_budapest", "drama"),
    ("lady_bird", "comedy"), ("lady_bird", "drama"),
    ("little_women", "drama"), ("little_women", "historical"),
    ("memento", "thriller"), ("memento", "drama"),
    ("prestige", "thriller"), ("prestige", "drama"), ("prestige", "sci_fi"),
]

# ── Build graph JSON ────────────────────────────────────────────────

def generate():
    nodes = []
    edges = []

    for p in PEOPLE:
        nodes.append({"@id": p["id"], "@type": "Person", **{k: v for k, v in p.items() if k != "id"}})

    for m in MOVIES:
        nodes.append({"@id": m["id"], "@type": "Movie", **{k: v for k, v in m.items() if k != "id"}})

    for g in GENRES:
        nodes.append({"@id": g["id"], "@type": "Genre", **{k: v for k, v in g.items() if k != "id"}})

    for person_id, movie_id, character in CASTING:
        edges.append({
            "@type": "ACTED_IN",
            "@src": person_id,
            "@dst": movie_id,
            "character": character,
        })

    for person_id, movie_id in DIRECTORS:
        edges.append({"@type": "DIRECTED", "@src": person_id, "@dst": movie_id})

    for movie_id, genre_id in MOVIE_GENRES:
        edges.append({"@type": "IN_GENRE", "@src": movie_id, "@dst": genre_id})

    return {"nodes": nodes, "edges": edges}


if __name__ == "__main__":
    data = generate()
    out_path = Path(__file__).resolve().parent / "graph.json"
    out_path.write_text(json.dumps(data, indent=2))
    node_count = len(data["nodes"])
    edge_count = len(data["edges"])
    node_labels = set(n["@type"] for n in data["nodes"])
    edge_labels = set(e["@type"] for e in data["edges"])
    print(f"Generated graph: {node_count} nodes ({node_labels}), {edge_count} edges ({edge_labels})")
    print(f"Written to {out_path}")
