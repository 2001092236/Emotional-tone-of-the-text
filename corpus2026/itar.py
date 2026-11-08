"""Research pilot of iterative additive regularization, eqs. (10)-(11), ITAR 2024.

This is an independently implemented *ITAR-inspired* experiment; not BigARTM
or the original authors' benchmark. It runs on the same 2026 corpora as the
baseline and NEVER claims expert-validated themes or causal change.

For fixed topics Phi_e: R_fix = tau * sum(Phi_e * log(Phi)).
For free topics: R_filter = -tau * sum(Phi_free * Phi_accepted/bad).
A hard-fixed safeguard after the M-step ensures accepted columns are exactly
preserved; the paper itself uses large finite-strength soft regularization.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.spatial.distance import jensenshannon
from scipy.sparse import csr_matrix

from .core import LEADERS, read_jsonl
from .topic_model import stratified_subset, token_matrix, artm_plsa, npmi_top_words, safe_tokenizer_language

PAPER = 'https://arxiv.org/abs/2408.05840'


def topic_similarity(a:np.ndarray,b:np.ndarray)->float:
    """Cosine similarity on normalized nonnegative word probabilities."""
    return float(np.dot(a,b)/max(1e-15,float(np.linalg.norm(a)*np.linalg.norm(b))))


def aligned_similarity(a:np.ndarray,b:np.ndarray)->float:
    """Permutation invariant topic stability, Hungarian matching."""
    if a.shape != b.shape or a.ndim != 2:
        raise ValueError('Same vocab and number of topics required')
    a0=a/np.maximum(np.linalg.norm(a,axis=0,keepdims=True),1e-15)
    b0=b/np.maximum(np.linalg.norm(b,axis=0,keepdims=True),1e-15)
    sim=a0.T@b0
    i,j=linear_sum_assignment(-sim)
    return float(np.mean(sim[i,j]))


def train_with_history(X:csr_matrix,K:int,iterations:int,seed:int,
                       fixed:list[np.ndarray],bad:list[np.ndarray],
                       fix_scale:float=.45,filter_scale:float=.075,
                       decor_scale:float=.015,hard_fix:bool=True):
    """PLSA EM with topic-fixation and topic-filtering derivatives.

    First len(fixed) columns preserve previously accepted good topics. E-step
    may redistribute document-topic weights. Free columns are penalized for
    overlapping previously seen good/bad topics. Independent of a GPU.
    """
    if len(fixed)>=K:
        raise ValueError('At least one free topic is required')
    D,V=X.shape
    rng=np.random.default_rng(seed)
    theta=rng.dirichlet(np.full(K,.5),size=D)
    phi=rng.dirichlet(np.full(V,.5),size=K).T
    f=len(fixed)
    if f:
        stack=np.stack(fixed,axis=1).astype(np.float64)
        if stack.shape!=(V,f) or np.any(stack<0):raise ValueError('fixed topics dimension mismatch')
        stack=stack/np.maximum(stack.sum(axis=0,keepdims=True),1e-15)
        phi[:,:f]=stack
    coo=X.tocoo()
    d,w=coo.row,coo.col
    weights=coo.data.astype(np.float64)
    n_total=float(weights.sum())
    good_sum=np.sum(np.stack(fixed,axis=1),axis=1) if fixed else np.zeros(V)
    bad_sum=np.sum(np.stack(bad,axis=1),axis=1) if bad else np.zeros(V)
    filter_word=good_sum+bad_sum
    for _ in range(iterations):
        posterior=theta[d,:]*phi[w,:]
        posterior/=np.maximum(posterior.sum(axis=1,keepdims=True),1e-25)
        posterior*=weights[:,None]
        ndt=np.column_stack([np.bincount(d,weights=posterior[:,j],minlength=D) for j in range(K)])
        nwt=np.column_stack([np.bincount(w,weights=posterior[:,j],minlength=V) for j in range(K)])
        theta=np.maximum(ndt-.1,1e-15)
        theta/=theta.sum(axis=1,keepdims=True)
        overlap=phi.sum(axis=1,keepdims=True)-phi
        contribution=nwt-.05-decor_scale*n_total*phi*overlap
        if f:
            # derivative phi * d/dphi (tau * phi_e * log phi) = tau*phi_e
            contribution[:,:f]+=fix_scale*n_total*stack
        if f < K and np.any(filter_word):
            # derivative of -tau sum_w,t_free,s in history phi[w,t]*phi_e[w,s]
            contribution[:,f:]-=filter_scale*n_total*phi[:,f:]*filter_word[:,None]
        phi=np.maximum(contribution,1e-15)
        phi/=phi.sum(axis=0,keepdims=True)
        if f and hard_fix:
            # Extra conservative guarantee; NOT part of original paper's soft R_fix.
            phi[:,:f]=stack
    return theta,phi


def coherence_summary(X:csr_matrix,phi:np.ndarray)->dict:
    per=np.asarray(npmi_top_words(X,phi))
    return {'mean_npmi':float(np.mean(per)),'min_npmi':float(per.min()),
            'topics_above_zero':int((per>0).sum()),'per_topic':per.tolist()}


def learn_topic_history(X:csr_matrix,words:np.ndarray,*,K:int=7,iterations:int=24,
                        rounds:int=4,seeds:tuple[int,...]=(11,23,37),
                        hard_fix:bool=True)->dict:
    """Fit independent ARTM baselines, then iteratively preserve good themes.

    Thresholds use 20/80 empirical percentiles of baseline coherence (as in
    ITAR methodology), plus positive coherence and Jensen-Shannon novelty.
    Monotonic accepted topic count is a property of the topic bank, NOT a
    statistical guarantee of better political interpretation.
    """
    if X.shape[0]<30 or X.shape[1]<K+3 or K<3 or rounds<1:
        raise ValueError('Insufficient matrix or invalid settings')
    if not seeds:raise ValueError('At least one baseline initialization is required')
    trained=[]
    for seed in seeds:
        theta,phi=artm_plsa(X,topics=K,iterations=iterations,seed=seed)
        coh=np.asarray(npmi_top_words(X,phi))
        trained.append((seed,theta,phi,coh))
    scores=np.concatenate([row[3] for row in trained])
    low=float(np.quantile(scores,.2))
    high=float(np.quantile(scores,.8))
    accepted=[];discarded=[];trace=[]
    independent_best=max(trained,key=lambda r:(int((r[3]>=high).sum()),float(r[3].mean())))
    baseline=trained[0]
    pairwise=[aligned_similarity(trained[i][2],trained[j][2]) for i in range(len(trained)) for j in range(i+1,len(trained))]
    for stage in range(rounds):
        if stage==0:
            seed,theta,phi,coh=independent_best
        else:
            theta,phi=train_with_history(X,K,iterations,seed=seeds[stage%len(seeds)]+stage*103,
                                          fixed=[x['vector'] for x in accepted],
                                          bad=discarded[-K:],hard_fix=hard_fix)
            coh=np.asarray(npmi_top_words(X,phi))
        previously=len(accepted)
        for i in np.argsort(-coh):
            if stage>0 and i<previously:continue
            vector=phi[:,i].copy()
            if len(accepted)>=K-1:break
            if float(coh[i])<max(high,0.0):continue
            if any(jensenshannon(vector,x['vector'],base=2)<.34 for x in accepted):continue
            accepted.append({'vector':vector,'coherence':float(coh[i]),'round':stage+1})
        for i in range(previously,K):
            if coh[i] <= low and len(discarded)<K*rounds:
                vector=phi[:,i].copy()
                if not any(jensenshannon(vector,old,base=2)<.2 for old in discarded):
                    discarded.append(vector)
        trace.append({'round':stage+1,'random_seed':int(seed if stage==0 else seeds[stage%len(seeds)]+stage*103),
                      'mean_npmi':round(float(coh.mean()),5),
                      'accepted_total':len(accepted),'accepted_added':len(accepted)-previously,
                      'filtered_bad_bank':len(discarded),'fixed_previous':previously})
        if len(accepted)>=K-1:break
    accepted_topics=[]
    for ix,entry in enumerate(accepted):
        vec=entry['vector'];top=np.argsort(vec)[-12:][::-1]
        accepted_topics.append({'id':f'itar_{ix+1}','accepted_round':entry['round'],
                                'coherence':round(entry['coherence'],5),
                                'keywords':[str(words[k]) for k in top]})
    topic_words=[item['keywords'][:10] for item in accepted_topics]
    diversity=len(set(w for arr in topic_words for w in arr))/(10*len(topic_words)) if topic_words else 0.
    return {
        'method':'ITAR-inspired: ARTM + R_fix(10) + R_filter(11) + hard fixation safeguard',
        'paper':PAPER,'replica_of_authors_code':False,
        'baseline_seed_count':len(trained),
        'baseline_stability_mean':round(float(np.mean(pairwise)) if pairwise else 1.,5),
        'baseline_stability_pairwise':[round(x,5) for x in pairwise],
        'baseline_best_mean_npmi':round(float(independent_best[3].mean()),5),
        'baseline_topic_count_over_threshold':int((independent_best[3]>=max(high,0)).sum()),
        'good_threshold_npmi':round(high,5), 'bad_threshold_npmi':round(low,5),
        'good_topics_accumulated':len(accepted),
        'good_topic_diversity_10':round(diversity,4),
        'topics':accepted_topics,'rounds':trace,
        'scientific_limitations':[
           'Coherence thresholds are in-sample baseline quantiles, not expert calibration',
           'Hard-fix safeguard differs from paper soft-only regularizer',
           'A monotone topic bank does not imply superior held-out predictive quality',
           'Short source texts are genre-specific, not direct psychological observations',
           'Cross-language and cross-source topic rankings are not valid'
        ]
    }


def build_report(data_dir:Path, out:Path,*,K:int=7,max_docs:int=900,iterations:int=22,rounds:int=4)->dict:
    result={'schema_version':1,'year':2026,'status':'experimental',
            'created_at':datetime.now(timezone.utc).isoformat(),
            'method':'ITAR-inspired independent pilot, not BigARTM or authors code',
            'paper':PAPER, 'leaders':{}}
    for leader in LEADERS:
        file=data_dir/f'{leader}.jsonl'
        rows=list(read_jsonl(file,leader).values())
        rows=[r for r in rows if len(r.get('text','').split())>=8]
        if len(rows)<60:
            result['leaders'][leader]={'status':'insufficient_data','source_rows':len(rows)}
            continue
        subset=stratified_subset(rows,max_docs)
        lang=safe_tokenizer_language(leader)
        X,vocabulary=token_matrix(subset,lang)
        keep=np.asarray((X>0).sum(axis=1)).ravel()>=3
        X=X[keep]
        subset=[r for r,k in zip(subset,keep) if k]
        if X.shape[0]<60 or X.shape[1]<K+5:
            result['leaders'][leader]={'status':'insufficient_processed_data','n':X.shape[0]}
            continue
        m=learn_topic_history(X,vocabulary,K=K,iterations=iterations,rounds=rounds)
        m.update({'status':'experimental','sample_documents':len(subset),
                  'language':lang,
                  'source_jsonl_sha256':hashlib.sha256(file.read_bytes()).hexdigest(),
                  'sample_date_min':min(x['date'] for x in subset),
                  'sample_date_max':max(x['date'] for x in subset),
                  'source_counts':{src:sum(r['source']==src for r in subset) for src in set(x['source'] for x in subset)}})
        result['leaders'][leader]=m
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--data-dir',type=Path,default=Path('data/2026'))
    p.add_argument('--out',type=Path,default=Path('docs/data/itar_experiment.json'))
    p.add_argument('--max-docs',type=int,default=900)
    p.add_argument('--topics',type=int,default=7)
    p.add_argument('--iterations',type=int,default=22)
    p.add_argument('--rounds',type=int,default=4)
    a=p.parse_args()
    report=build_report(a.data_dir,a.out,K=a.topics,max_docs=a.max_docs,iterations=a.iterations,rounds=a.rounds)
    for leader,m in report['leaders'].items():
        print(leader,m.get('status'),m.get('good_topics_accumulated'),m.get('baseline_stability_mean'))

if __name__=='__main__':main()
