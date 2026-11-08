"""Reproducible multilingual topic benchmark for the 2026 political-text corpus.

Never publish a 'winner' without 20 completed trials per leader, successful
distinct algorithms / GPU encoders, and document-grounded label verification.
GPU inference is local; full texts are never sent to external APIs by default.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import tempfile
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix, hstack
from sklearn.cluster import KMeans
from sklearn.decomposition import LatentDirichletAllocation, NMF, TruncatedSVD
from sklearn.feature_extraction.text import CountVectorizer, TfidfTransformer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import normalize

from .core import LEADERS, read_jsonl
from .topic_model import artm_plsa, stratified_subset
from .itar import learn_topic_history

LANGUAGES = {"trump": "en", "putin": "ru", "zelenskyy": "uk"}
SPACY = {"en": "en_core_web_sm", "ru": "ru_core_news_sm", "uk": "uk_core_news_sm"}
ENCODERS = (
    "Qwen/Qwen3-Embedding-0.6B",
    "BAAI/bge-m3",
    "intfloat/multilingual-e5-large-instruct",
)
# Canonicalize only linguistic equivalents within each language. Do NOT equate
# the politically distinct descriptions "war", "СВО" and "invasion".
ENTITY_RULES = {
    "en": [
        (r"\b(?:united states of america|united states|u\.s\.a?\.?)\b", "term_usa"),
        (r"\b(?:north atlantic treaty organization|nato)\b", "term_nato"),
        (r"\b(?:european union|e\.u\.)\b", "term_eu"),
    ],
    "ru": [
        (r"\b(?:соедин[её]нн(?:ые|ых) штаты(?: америки)?|сша)\b", "term_usa"),
        (r"\b(?:североатлантический альянс|нато)\b", "term_nato"),
        (r"\b(?:европейский союз|евросоюз|ес)\b", "term_eu"),
        (r"\b(?:специальн(?:ая|ой|ую) военн(?:ая|ой|ую) операци(?:я|и|ю)|сво)\b", "term_svo"),
    ],
    "uk": [
        (r"\b(?:сполучен(?:і|их) штат(?:и|ів)(?: америки)?|сша)\b", "term_usa"),
        (r"\b(?:північноатлантичний альянс|нато)\b", "term_nato"),
        (r"\b(?:європейський союз|євросоюз|єс)\b", "term_eu"),
    ],
}
DISPLAY_TERMS = {
    "term_usa": "США", "term_nato": "НАТО",
    "term_eu": "ЕС", "term_svo": "СВО",
}
# Boilerplate, stylistic fillers and salutation formulas are not topics.
GENERIC = {
    "en": set("great thanks thank wonderful amazing fantastic biggest total always congratulations truly really everyone today".split()),
    "ru": set("подробнее смотреть видео подписаться здравствуйте дорогой уважаемый глава провёл прошёл".split()),
    "uk": set("дивитися відео читати посилання дякую всім вітаю".split()),
}


def clean_entities(raw: str, language: str) -> str:
    s = re.sub(r"https?://\S+|www\.\S+|@[A-Za-z0-9_]+", " ", raw or "", flags=re.I)
    s = s.lower().replace("\u00a0", " ")
    for pattern, replacement in ENTITY_RULES[language]:
        s = re.sub(pattern, " " + replacement + " ", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip()


def clean_rows(data_dir: Path, leader: str, cap: int) -> tuple[list[dict], dict]:
    raw = list(read_jsonl(data_dir / (leader + ".jsonl"), leader).values())
    chosen, seen, issues = [], set(), Counter()
    language = LANGUAGES[leader]
    for r in sorted(raw, key=lambda z: (z["date"], z["id"])):
        s = r.get("text", "")
        if not isinstance(s, str) or len(s.split()) < 8:
            issues["too_short"] += 1
            continue
        if r.get("is_repost"):
            issues["repost"] += 1
            continue
        if r.get("language") and r["language"] not in {language, language + "-UK", language + "-RU", language + "-US"}:
            issues["language_metadata"] += 1
            continue
        letters = re.findall("[a-zA-Zа-яёіїєґ]", s.lower())
        relevant = sum(bool(re.fullmatch("[a-z]", c)) for c in letters) if language == "en" else sum(bool(re.fullmatch("[а-яёіїєґ]", c)) for c in letters)
        if not letters or relevant / len(letters) < .67:
            issues["script_mismatch"] += 1
            continue
        canonical = clean_entities(s, language)
        unique = hashlib.sha256(canonical.encode("utf8")).hexdigest()
        if unique in seen:
            issues["exact_duplicate"] += 1
            continue
        seen.add(unique)
        chosen.append(r)
    if len(chosen) > cap:
        chosen = stratified_subset(chosen, cap)
    if len(chosen) < 90:
        raise ValueError("Not enough original-language non-duplicate documents for " + leader)
    return chosen, {"raw": len(raw), "usable": len(chosen), "excluded": dict(issues)}


def lemmatize(rows: list[dict], language: str, min_count: int = 4) -> tuple[list[str], list[list[str]], dict]:
    import spacy
    from gensim.models.phrases import Phrases, Phraser
    try:
        nlp = spacy.load(SPACY[language], disable=["ner", "parser"])
    except OSError as e:
        raise RuntimeError("Mandatory model absent: python -m spacy download " + SPACY[language]) from e
    nlp.max_length = 250000
    cleaned = [clean_entities(r["text"], language) for r in rows]
    documents = []
    unknown = 0
    for doc in nlp.pipe(cleaned, batch_size=32):
        toks = []
        for w in doc:
            if w.is_space or w.is_punct or w.is_stop or w.like_url:
                continue
            # Preserve artificial entity placeholder even if spaCy POS-tags it oddly.
            if w.text.startswith("term_"):
                v = w.text
            else:
                v = (w.lemma_ or w.text).strip().lower()
                if w.pos_ not in {"NOUN", "PROPN", "ADJ", "VERB"}:
                    continue
            if not re.fullmatch(r"[\w_]{3,}", v, flags=re.UNICODE):
                continue
            if v in GENERIC[language] or v in {"http", "https", "com", "www"}:
                continue
            if v == w.text.lower() and not w.lemma_:
                unknown += 1
            toks.append(v)
        documents.append(toks)
    # Statistical phrase mining (not all adjacent words must be fused).
    phrase = Phraser(Phrases(documents, min_count=min_count, threshold=9.0, scoring="default", delimiter="_"))
    tokens = [phrase[d] for d in documents]
    return [" ".join(t) for t in tokens], tokens, {"blank_lemmas": unknown, "phrases": sum("_" in x and not x.startswith("term_") for t in tokens for x in t)}


def display_term(term: str) -> str:
    if term in DISPLAY_TERMS:
        return DISPLAY_TERMS[term]
    return " ".join(DISPLAY_TERMS.get(word, word) for word in term.split("_"))


def vectors(texts: list[str], min_df: int = 4, max_features: int = 4800):
    cv = CountVectorizer(lowercase=False, token_pattern=r"(?u)\b[\w_]{3,}\b",
                         min_df=min_df, max_df=.68, max_features=max_features)
    X = cv.fit_transform(texts).tocsr().astype(np.float64)
    return X, np.asarray(cv.get_feature_names_out())


def ctfidf(X: csr_matrix, assignments: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    # From cluster labels to words and one-hot topic assignment.
    valid = assignments >= 0
    if valid.sum() < 50 or len(set(assignments[valid])) < 2:
        raise ValueError("All-outlier or collapsed clustering")
    groups = sorted(set(assignments[valid]))
    labels = {old: i for i, old in enumerate(groups)}
    W = np.zeros((X.shape[0], len(groups)), dtype=float)
    for i, label in enumerate(assignments):
        if label in labels:
            W[i, labels[label]] = 1.
    H = W.T @ X
    H = np.asarray(H)
    tf = H / np.maximum(H.sum(axis=1, keepdims=True), 1.)
    idf = np.log(1 + X.shape[0] / np.maximum(1., (X > 0).sum(axis=0).A1))
    return W, tf * idf[None, :]


def gpu_embeddings(rows: list[dict], name: str, cache_dir: Path, language: str) -> np.ndarray:
    import torch
    from sentence_transformers import SentenceTransformer
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU required; no silent CPU replacement")
    ids = "|".join(r["id"] for r in rows)
    key = hashlib.sha256((name + language + ids).encode()).hexdigest()[:20]
    path = cache_dir / ("emb-" + key + ".npy")
    if path.exists():
        return np.load(path)
    cache_dir.mkdir(parents=True, exist_ok=True)
    model = SentenceTransformer(name, device="cuda", trust_remote_code=False)
    model.max_seq_length = min(512, model.max_seq_length)
    embedding = model.encode(
        [r["text"][:12000] for r in rows], batch_size=16,
        show_progress_bar=False, normalize_embeddings=True,
        convert_to_numpy=True,
    ).astype(np.float32)
    np.save(path, embedding)
    del model
    torch.cuda.empty_cache()
    return embedding


def fit(algo: str, X: csr_matrix, tfidf: csr_matrix, vocab: np.ndarray,
        rows: list[dict], k: int, seed: int, strength: float, E: np.ndarray | None = None, processed: list[str] | None = None, encoder_name: str | None = None):
    if algo == "nmf":
        model = NMF(n_components=k, init="nndsvda", random_state=seed,
                    max_iter=220, alpha_W=strength, alpha_H=.005, l1_ratio=.2)
        W = model.fit_transform(tfidf)
        return W, model.components_, {"reconstruction_error": float(model.reconstruction_err_)}
    if algo == "lda":
        model = LatentDirichletAllocation(
            n_components=k, random_state=seed, max_iter=14, learning_method="batch",
            doc_topic_prior=strength, topic_word_prior=.1, n_jobs=1)
        W = model.fit_transform(X)
        return W, model.components_, {"perplexity_train": float(model.perplexity(X))}
    if algo == "plsa_artm_lite":
        theta, phi = artm_plsa(X, topics=k, iterations=24,
                               alpha=-strength, beta=-.07,
                               decorrelation_ratio=.012, seed=seed)
        return theta, phi.T, {"implementation": "ARTM-inspired, not official BigARTM"}
    if algo == "svd_kmeans":
        Z = TruncatedSVD(n_components=min(72, X.shape[1] - 1), random_state=seed).fit_transform(tfidf)
        ids = KMeans(n_clusters=k, random_state=seed, n_init=8).fit_predict(normalize(Z))
        W, H = ctfidf(X, ids, k)
        return W, H, {}
    if algo == "btm":
        import bitermplus as btm
        btm_docs = btm.get_vectorized_docs(processed, vocab)
        pairs = btm.get_biterms(btm_docs, win=12)
        model = btm.BTM(X.astype(np.int32), vocab.tolist(), T=k, seed=seed)
        model.fit(pairs, iterations=80)
        W = model.transform(btm_docs, verbose=False)
        H = np.asarray(model.matrix_topics_words_)
        return W, H, {}
    if algo == "itar":
        outcome = learn_topic_history(X, vocab, K=k, iterations=17,
                                      rounds=3, seeds=(seed, seed + 11, seed + 29))
        topics = outcome["topics"]
        if len(topics) < 2:
            raise ValueError("ITAR returned fewer than two distinct themes")
        H = np.zeros((len(topics), len(vocab)))
        lookup = {w: i for i, w in enumerate(vocab)}
        for t, item in enumerate(topics):
            for rank, word in enumerate(item["keywords"]):
                H[t, lookup[word]] = 1 / (rank + 1)
        W = np.asarray(X @ H.T)
        return W, H, {"topic_count_from_bank": len(topics), "replica_of_paper": False}
    if algo == "bigartm":
        import artm
        with tempfile.TemporaryDirectory(prefix="artm_") as td:
            root = Path(td)
            nonzero = X.tocoo()
            with (root / "docword.corpus.txt").open("w", encoding="utf8") as f:
                f.write("%d\n%d\n%d\n" % (X.shape[0], X.shape[1], nonzero.nnz))
                for d, w, count in zip(nonzero.row, nonzero.col, nonzero.data):
                    f.write("%d %d %d\n" % (d+1, w+1, round(count)))
            (root / "vocab.corpus.txt").write_text("\n".join(vocab) + "\n", encoding="utf8")
            batches = artm.BatchVectorizer(data_path=str(root), data_format="bow_uci",
                                           collection_name="corpus", target_folder=str(root / "batches"))
            dictionary = artm.Dictionary()
            dictionary.gather(data_path=batches.data_path)
            model = artm.ARTM(num_topics=k, dictionary=dictionary,
                              seed=seed, cache_theta=True)
            model.regularizers.add(artm.SmoothSparsePhiRegularizer(name="sparse", tau=-strength))
            model.regularizers.add(artm.DecorrelatorPhiRegularizer(name="decor", tau=strength * 15))
            model.fit_offline(batch_vectorizer=batches, num_collection_passes=18)
            df = model.get_phi()
            phi = np.zeros((k, X.shape[1]), dtype=float)
            ix = {str(term): i for i, term in enumerate(vocab)}
            for token, values in df.iterrows():
                key = token[1] if isinstance(token, tuple) else token
                if key in ix:
                    phi[:, ix[key]] = values.to_numpy()
            W = np.asarray(X @ phi.T)
            return W, phi, {"implementation": "BigARTM C++"}
    if E is None:
        raise ValueError("Embedding model required for algorithm " + algo)
    if algo == "embedding_kmeans":
        ids = KMeans(n_clusters=k, n_init=12, random_state=seed).fit_predict(E)
        W, H = ctfidf(X, ids, k)
        return W, H, {}
    if algo == "bertopic_hdbscan":
        from bertopic import BERTopic
        from umap import UMAP
        from hdbscan import HDBSCAN
        model = BERTopic(
            embedding_model=None, calculate_probabilities=False, verbose=False,
            umap_model=UMAP(n_neighbors=int(strength), n_components=5, min_dist=0.0,
                            metric="cosine", random_state=seed),
            hdbscan_model=HDBSCAN(min_cluster_size=max(15, k * 3),
                                   min_samples=max(5, k // 2), prediction_data=False),
        )
        clusters, _ = model.fit_transform([r["text"] for r in rows], E)
        W, H = ctfidf(X, np.array(clusters), k)
        return W, H, {"topics_found": int(H.shape[0]), "outlier_fraction": float(np.mean(np.array(clusters) < 0))}
    if algo == "ctm_combined":
        from contextualized_topic_models.models.ctm import CombinedTM
        from contextualized_topic_models.utils.data_preparation import TopicModelDataPreparation
        # Import uses the same BoW and exactly the same externally cached embeddings.
        prep = TopicModelDataPreparation()
        data = prep.load(E, X.astype(np.float32), {i: str(w) for i, w in enumerate(vocab)})
        model = CombinedTM(bow_size=X.shape[1], contextual_size=E.shape[1],
                           n_components=k, num_epochs=35)
        model.fit(data, verbose=False)
        W = model.get_doc_topic_distribution(data, n_samples=5)
        H = np.zeros((k, X.shape[1]))
        lookup = {str(w): i for i, w in enumerate(vocab)}
        for t, terms in enumerate(model.get_topic_lists(30)):
            for rank, word in enumerate(terms):
                if word in lookup:
                    H[t, lookup[word]] = 1 / (rank + 1)
        return W, H, {}
    if algo == "top2vec":
        from top2vec import Top2Vec
        from sentence_transformers import SentenceTransformer
        import torch
        model_embed = SentenceTransformer(encoder_name, device="cuda")
        model = Top2Vec(
            documents=processed,
            embedding_model=lambda docs: model_embed.encode(docs, show_progress_bar=False),
            min_count=3, workers=2, ngram_vocab=True, verbose=False,
            umap_args={"n_neighbors": 15, "n_components": 5, "metric": "cosine"},
            hdbscan_args={"min_cluster_size": 15},
        )
        words, scores, numbers = model.get_topics()
        ids = model.get_documents_topics(doc_ids=list(range(X.shape[0])))[0]
        W, H = ctfidf(X, np.asarray(ids), len(numbers))
        del model_embed
        torch.cuda.empty_cache()
        return W, H, {"topics_found": len(numbers)}
    raise ValueError("Unknown algorithm " + algo)


def topic_npmi(X: csr_matrix, H: np.ndarray, top_k: int = 10) -> list[float]:
    """Document co-occurrence NPMI; use a shared reference set per leader."""
    B = X.copy().tocsr()
    B.data[:] = 1
    N = X.shape[0]
    out = []
    for weights in H:
        words = np.argsort(weights)[::-1][:top_k]
        block = B[:, words].astype(np.float64).toarray()
        count = block.sum(axis=0)
        matrix = block.T @ block
        scores = []
        for a in range(len(words)):
            for b in range(a + 1, len(words)):
                xy = matrix[a, b]
                if xy < 1 or xy == N:
                    scores.append(-1. if xy < 1 else 0.)
                else:
                    p_ab = xy / N
                    scores.append(float(np.log(p_ab / ((count[a]/N)*(count[b]/N))) / -np.log(p_ab)))
        out.append(float(np.mean(scores)) if scores else -1.)
    return out


def evaluate(X: csr_matrix, W: np.ndarray, H: np.ndarray, vocab: np.ndarray) -> dict:
    W, H = np.asarray(W, float), np.asarray(H, float)
    if W.shape[0] != X.shape[0] or H.shape[1] != X.shape[1] or W.shape[1] != H.shape[0]:
        raise ValueError("Inconsistent document/topic/word matrices")
    good = (H.sum(axis=1) > 1e-10) & (W.sum(axis=0) > 1e-10)
    H, W = H[good], W[:, good]
    if H.shape[0] < 2:
        raise ValueError("Degenerate topics")
    top = [vocab[np.argsort(h)[::-1][:10]].tolist() for h in H]
    sets = [set(a) for a in top]
    overlaps = [len(a&b)/max(1, len(a|b)) for i, a in enumerate(sets) for b in sets[i+1:]]
    npmis = topic_npmi(X, H)
    W = W/np.maximum(W.sum(axis=1, keepdims=True), 1e-12)
    support = (W.argmax(axis=1)).tolist()
    sizes = [support.count(i) for i in range(H.shape[0])]
    diversity = len(set(w for ts in top for w in ts)) / sum(len(ts) for ts in top)
    duplicated = sum(float(x >= .45) for x in overlaps) / max(1, len(overlaps))
    small = sum(x < max(8, int(.012 * X.shape[0])) for x in sizes)
    # Coherence alone is gameable: reward distinct themes and document support.
    score = (0.45 * float(np.mean(npmis)) + 0.30 * diversity
             + 0.15 * (1 - duplicated) + 0.10 * (1 - small / H.shape[0]))
    return {"score_proxy": round(score, 5),
            "npmi_mean": round(float(np.mean(npmis)), 5),
            "npmi_per_topic": [round(x, 5) for x in npmis],
            "topic_diversity_10": round(diversity, 5),
            "duplicate_pair_ratio": round(duplicated, 5),
            "max_topword_jaccard": round(max(overlaps, default=0), 5),
            "min_topic_documents": int(min(sizes)),
            "topic_count": int(H.shape[0]),
            "topics": [{"id": "topic_%02d" % (i+1), "keywords": [display_term(x) for x in t],
                        "coherence_npmi": round(npmis[i], 5),
                        "documents": int(sizes[i])} for i, t in enumerate(top)],
            "assignment": support, "topic_proportions": list(map(float, W.mean(axis=0)))}


def evidence(trial: dict, rows: list[dict], n: int = 5) -> list[dict]:
    topics = trial["metrics"]["topics"]
    assignments = trial["metrics"]["assignment"]
    for i, topic in enumerate(topics):
        matches = [r for r, assigned in zip(rows, assignments) if assigned == i]
        # Stable sample across months, rather than highest probability templates.
        examples = sorted(matches, key=lambda x: (x["date"][:7], x["id"]))
        if len(examples) > n:
            idx = np.linspace(0, len(examples)-1, n, dtype=int)
            examples = [examples[z] for z in idx]
        topic["examples"] = [
            {"id": r["id"], "date": r["date"], "url": r.get("url", ""),
             "title": r.get("title", "")}
            for r in examples
        ]
        topic["name_ru"] = None
        topic["description_ru"] = None
        topic["validation"] = "requires_document_grounded_semantic_review"
    return topics


def configurations(mode: str) -> list[tuple[str, int, int, float, str | None]]:
    config = []
    for k in (6, 9, 12, 15):
        for reg in (0.0, .015):
            config.append(("nmf", k, 17, reg, None))
        for prior in (.12, .45):
            config.append(("lda", k, 17, prior, None))
        for penalty in (.09, .3):
            config.append(("plsa_artm_lite", k, 17, penalty, None))
        config.append(("svd_kmeans", k, 17, 0., None))
    config += [("itar", 9, 17, .1, None), ("btm", 9, 17, .1, None),
               ("bigartm", 9, 17, .1, None)]
    if mode == "full":
        for encoder in ENCODERS:
            for k in (6, 10, 14):
                config.append(("embedding_kmeans", k, 17, 0., encoder))
            for nb in (10, 20):
                config.append(("bertopic_hdbscan", 8, 17, nb, encoder))
            for k in (8, 12):
                config.append(("ctm_combined", k, 17, 0., encoder))
            config.append(("top2vec", 8, 17, 0., encoder))
    return config


def run(args) -> dict:
    report = {"schema_version": 2, "year": 2026,
              "created_at": datetime.now(timezone.utc).isoformat(),
              "mode": args.mode,
              "status": "incomplete",
              "critical_note": "No empirical GPU results until a CUDA runner successfully finishes; LLM naming is pending without local endpoint.",
              "models_hf": list(ENCODERS), "scientific_methods": [
                  "LDA", "NMF", "ARTM-inspired pLSA", "SVD+k-means", "ITAR-inspired",
                  "BTM", "BigARTM C++", "Embedding k-means",
                  "BERTopic HDBSCAN", "CombinedTM", "Top2Vec"],
              "leaders": {}}
    for leader in LANGUAGES:
        rows, coverage = clean_rows(args.data_dir, leader, args.max_docs)
        processed, tokens, linguistic = lemmatize(rows, LANGUAGES[leader])
        good = [bool(x.strip()) for x in processed]
        rows = [r for r, ok in zip(rows, good) if ok]
        processed = [s for s, ok in zip(processed, good) if ok]
        X, vocab = vectors(processed, min_df=3 if len(rows) < 600 else 4)
        tfidf = TfidfTransformer(sublinear_tf=True).fit_transform(X)
        by_model: dict[str, np.ndarray] = {}
        attempts, completed = [], []
        for index, (algo, k, seed, strength, encoder) in enumerate(configurations(args.mode)):
            trial = {"trial_id": index + 1, "algorithm": algo, "topics_requested": k,
                     "seed": seed, "strength": strength, "hf_encoder": encoder}
            try:
                if encoder and encoder not in by_model:
                    by_model[encoder] = gpu_embeddings(rows, encoder, args.cache_dir, LANGUAGES[leader])
                W, H, extras = fit(algo, X, tfidf, vocab, rows, k, seed, strength,
                                   by_model.get(encoder), processed, encoder)
                metric = evaluate(X, W, H, vocab)
                trial.update({"status": "completed", "metrics": metric, "details": extras})
                completed.append(trial)
            except Exception as exc:
                trial.update({"status": "failed", "error": "%s: %s" % (type(exc).__name__, exc)})
            attempts.append(trial)
            print(leader, trial["trial_id"], algo, trial["status"],
                  trial.get("metrics", {}).get("score_proxy"), flush=True)
        completed.sort(key=lambda t: (t["metrics"]["score_proxy"],
                                      t["metrics"]["npmi_mean"]), reverse=True)
        for trial in completed[:5]:
            evidence(trial, rows)
        algos = sorted(set(t["algorithm"] for t in completed))
        encoders = sorted(set(t["hf_encoder"] for t in completed if t["hf_encoder"]))
        quality = (len(completed) >= 20 and len(algos) >= 7
                   and len(encoders) >= 3 and
                   completed[0]["metrics"]["duplicate_pair_ratio"] <= .15)
        report["leaders"][leader] = {
            "status": "awaiting_semantic_approval" if quality else "incomplete",
            "coverage": coverage, "linguistics": linguistic,
            "sample_documents": len(rows), "vocabulary_size": len(vocab),
            "source_sha256": hashlib.sha256((args.data_dir / (leader+".jsonl")).read_bytes()).hexdigest(),
            "completed_trials": len(completed), "requested_trials": len(attempts),
            "completed_algorithms": algos, "completed_gpu_encoders": encoders,
            "top_trials": [{**{k: v for k, v in t.items() if k != "metrics"},
                            "metrics": {key: val for key, val in t["metrics"].items() if key != "assignment"}}
                           for t in completed[:5]],
            "all_trials": [{key: val for key, val in t.items() if key != "metrics"} |
                           ({"metrics": {key: val for key, val in t["metrics"].items()
                                         if key not in {"assignment", "topics"}}} if "metrics" in t else {})
                           for t in attempts],
            "acceptance_gate_pass": quality,
        }
    if all(d["acceptance_gate_pass"] for d in report["leaders"].values()):
        report["status"] = "awaiting_semantic_approval"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", type=Path, default=Path("data/2026"))
    p.add_argument("--out", type=Path, default=Path("docs/data/topic_lab_2026.json"))
    p.add_argument("--max-docs", type=int, default=900)
    p.add_argument("--mode", choices=("cpu", "full"), default="cpu")
    p.add_argument("--cache-dir", type=Path, default=Path(".cache/topic_lab"))
    args = p.parse_args()
    result = run(args)
    print(result["status"], {leader: d["completed_trials"] for leader, d in result["leaders"].items()})


if __name__ == "__main__":
    main()
