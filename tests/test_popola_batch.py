import pytest

from scripts.popola_batch import classifica_caso


def test_classifica_caso_nessun_nome():
    assert classifica_caso([], ["volto_finto"]) == "iptc_mancante"


def test_classifica_caso_nessun_volto():
    assert classifica_caso(["Mario Rossi"], []) == "nessun_volto"


def test_classifica_caso_piu_volti_un_nome():
    assert classifica_caso(["Mario Rossi"], ["volto1", "volto2"]) == "volti_multipli"


def test_classifica_caso_un_volto_piu_nomi():
    assert (
        classifica_caso(["Mario Rossi", "Anna Bianchi"], ["volto1"]) == "volti_multipli"
    )


def test_classifica_caso_pulito_un_volto_un_nome():
    assert classifica_caso(["Mario Rossi"], ["volto1"]) is None
