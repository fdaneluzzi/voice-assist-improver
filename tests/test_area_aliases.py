from voice_assist_improver.ha.area_aliases import generate, pt_preposition, split_name


def ent(i, name, area, domain="light", **kw):
    return {"id": f"{domain}.{i}", "domain": domain, "name": name, "area": area, "aliases": [], "device_class": None, **kw}


def test_split_name_prefix_and_suffix():
    assert split_name("Sala Pendente", "Sala") == "Pendente"
    assert split_name("Janela Escritório", "Escritório") == "Janela"
    assert split_name("Garagem Arandela Porta", "Garagem") == "Arandela Porta"
    assert split_name("Ar da suíte", "Suite") is None
    assert split_name("Sala", "Sala") is None


def test_pt_preposition():
    areas = ("Sala", "Cozinha", "Suite", "Garagem", "Escritório", "Quintal", "Quarto Felipe", "Hall")
    assert [pt_preposition(a) for a in areas] == ["da", "da", "da", "da", "do", "do", "do", "do"]


def test_generates_natural_pt_br_aliases():
    ents = [ent("a", "Sala Pendente", "Sala"), ent("b", "Cozinha Luz Central", "Cozinha"),
            ent("c", "Janela Escritório", "Escritório", "cover"), ent("d", "Int Gar Dir 3", "Garagem")]
    got = {g["entity_id"]: g["alias"] for g in generate(ents, "pt-BR")}
    assert got == {"light.a": "pendente da sala", "light.b": "luz central da cozinha", "cover.c": "janela do escritório"}


def test_other_languages_produce_nothing():
    # English Assist already understands "the pendant in the living room" natively.
    assert generate([ent("a", "Sala Pendente", "Sala")], "en") == []


def test_duplicates_are_dropped_not_guessed():
    assert generate([ent("a", "Sala Led", "Sala"), ent("b", "Sala  LED", "Sala")]) == []


def test_only_domains_with_natural_area_names_get_rule_aliases():
    ents = [ent("l", "Sala Porta", "Sala", "lock"), ent("s", "Sala Tomada", "Sala", "switch")]
    assert generate(ents) == []


def test_skips_alias_equal_to_another_entity_name():
    ents = [ent("a", "Sala Pendente", "Sala"), ent("b", "Pendente da Sala", "Quintal")]
    assert all(g["entity_id"] != "light.a" for g in generate(ents))
