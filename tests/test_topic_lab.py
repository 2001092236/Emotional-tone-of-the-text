"""Regression checks for the multilingual research branch (no network or GPU)."""
import numpy as np
from scipy.sparse import csr_matrix
from corpus2026.topic_lab import (
    ENCODERS, LANGUAGES, clean_entities, configurations,
    merge_duplicate_topics, evaluate, display_term,
)
from corpus2026.topic_review import evaluate_label


def test_phrases_and_entities():
    assert "term_usa" in clean_entities("Обсуждение США и Соединённых Штатах", "ru")
    assert "term_usa" in clean_entities("У Сполучених Штатах обговорили допомогу", "uk")
    assert "term_usa" in clean_entities("The United States is discussing sanctions", "en")
    assert "term_nato" in clean_entities("Партнёры НАТО выступили", "ru")
    assert "term_svo" in clean_entities("Специальной военной операции", "ru")
    assert "term_svo" not in clean_entities("Полномасштабное вторжение и война", "ru")
    assert display_term("term_usa") == "США"


def test_more_than_20_unique_cpu_configs_each_leader():
    grid = configurations("cpu")
    assert len(grid) >= 20
    assert len(set(grid)) == len(grid)
    assert len(LANGUAGES) >= 3
    all_grid = configurations("full")
    assert len(all_grid) > len(grid)
    assert set(row[4] for row in all_grid if row[4]) == set(ENCODERS)


def test_topic_merge_before_evaluation():
    w = np.ones((12, 3))
    h = np.array([[2., 1., 1., 0., 0., 0.],
                  [2., 1., 1., 0., 0., 0.],
                  [0., 0., 0., 3., 2., 1.]])
    w1, h1, merged = merge_duplicate_topics(w, h)
    assert merged >= 1
    assert h1.shape[0] == w1.shape[1] == 2


def test_topic_label_must_cite_originals():
    reply = {"name_ru": "Переговоры о прекращении военных действий",
             "description_ru": "Обсуждаются предложения о прекращении боевых действий и посредничестве.",
             "semantic_coherence": 5, "label_faithfulness": 5,
             "distinctness": 5, "political_substantiveness": 5,
             "evidence_ids": ["a", "b"], "is_template_or_style": False}
    assert evaluate_label(reply, {"a", "b"}, [])["valid"]
    assert not evaluate_label(reply, {"a"}, [])["valid"]
    assert not evaluate_label(reply, {"a", "b"}, [reply["name_ru"]])["valid"]
    reply["is_template_or_style"] = True
    assert not evaluate_label(reply, {"a", "b"}, [])["valid"]
