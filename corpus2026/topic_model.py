"""ARTM-inspired regularized PLSA: sparse/smooth and decorrelation M-step.

Reproducible CPU-only 2026 experiment. This is NOT BigARTM or ITAR.
Its additive regularizers follow the generic EM update discussed in:
  Vorontsov & Potapenko (2012); Gorbulev, Alekseev & Vorontsov (2024).
We also fit an NMF baseline, report coherence and topic diversity.
Each leader is modelled separately; cross-language topic alignment is NOT implied.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix
from sklearn.decomposition import NMF
from sklearn.feature_extraction.text import CountVectorizer, TfidfTransformer

from .core import LEADERS, read_jsonl

# This deliberately conservative multilingual stoplist will need linguistic review.
# It excludes common grammatical words only, not politically meaningful lexemes.
STOPWORDS = {
 'en': '''a about above after again against all am an and any are as at be because been before being below between both but by can could did do does doing down during each few for from further had has have having he her here hers herself him himself his how i if in into is it its itself just me more most my myself no nor not of off on once only or other our ours ourselves out over own same she should so some such than that the their theirs them themselves then there these they this those through to too under until up very was we were what when where which while who whom why will with would you your yours yourself yourselves says said also would shall may many every one two three today now new day days years year see let us they our has for it from this'''.split(),
 'ru': '''а без более бы был была были было быть в вам вас весь во вот все всего всею всех вы где да даже для до его ее ей ему если есть еще же за и из или им их к как какое какой когда кого который которые кто ли либо мне мной мог могла могли может можно мы на над нам нас не него неё ней нем нет ни но о об обо он она они оно от по под после при про раз с сам сама сами свое своей свои свой себя себе сейчас со так такая такие такой там те тебе тем теми теперь тех то того тоже той только том тот ту ты у уже хотя чем через что чтобы чья эта эти это этот эту я её мой мои моих меня мне как все был также далее потом кроме все также между на самом тут они бы а ведь что же сам это еще даже год года году лет время день дня день спасибо привет'''.split(),
 'uk': '''а аби але або аж без був була були було бути в вам вас ваш ваша ваше ваші ваших весь вже ви від він вона вони воно всіх все всі всього де для до дуже його її їм їх із і й є ще ж за і з як якби який яка які якій коли кого кому котрий краще маємо ми мій мною на нам нас не немає ним них ні ну о об ось от перед після по під при про раз року роки рік років це цих ці цей ця що щоб також та так такий такі там те тепер тих тільки тим то той тут ти у це ця цей цими сьогодні вже дякую нас наша нашого ми будемо мають'''.split(),
}


# These terms are disproportionately frequent in channel templates and would
# produce topics about publication mechanics, not political content.
BOILERPLATE = {
 'en': {'http','https','www','com','donald','trump','president','truthsocial'},
 'ru': {'сайте','кремля','подробнее','видео','ролик','полное','путин','владимир',
        'президента','президент','пресс','секретаря','конференс','колл','пескова',
        'rutube','смотреть','подписывайтесь'},
 'uk': {'президента','президент','зеленський','зеленського','посилання','читати',
        'відео','дивіться','каналі','телеграм'},
}


def strip_web_boilerplate(text: str) -> str:
    text = re.sub(r'https?://\S+|www\.\S+', ' ', text, flags=re.I)
    text = re.sub(r'@[A-Za-z0-9_]+', ' ', text)
    return text


def safe_tokenizer_language(leader: str) -> str:
    return {'trump':'en','putin':'ru','zelenskyy':'uk'}[leader]


def stratified_subset(rows: list[dict], limit: int) -> list[dict]:
    """Deterministically cap monthly samples so recent busy months do not dominate."""
    if len(rows) <= limit:
        return rows
    by_month: dict[str,list[dict]]=defaultdict(list)
    for row in rows:
        by_month[row['date'][:7]].append(row)
    months=sorted(by_month)
    selected=[]
    first=max(1,limit//len(months))
    for month in months:
        items=sorted(by_month[month],key=lambda d: hashlib.sha256(d['id'].encode()).hexdigest())
        selected.extend(items[:first])
    chosen={d['id'] for d in selected}
    leftovers=[d for d in rows if d['id'] not in chosen]
    leftovers.sort(key=lambda d:hashlib.sha256(d['id'].encode()).hexdigest())
    return (selected+leftovers[:max(0,limit-len(selected))])[:limit]


def token_matrix(rows: list[dict], language: str, max_features: int = 2400):
    # Note: proper nouns are NOT in stopwords, which is intentional for discourse analysis.
    pattern = r'(?u)\b[a-z]{3,}\b' if language == 'en' else r'(?u)\b[а-яёіїєґ]{3,}\b'
    vectorizer=CountVectorizer(lowercase=True,token_pattern=pattern,
                               stop_words=sorted(set(STOPWORDS[language])|BOILERPLATE[language]),
                               min_df=max(3,int(len(rows)*.002)),max_df=.70,max_features=max_features)
    X=vectorizer.fit_transform([strip_web_boilerplate(row['text']) for row in rows]).tocsr().astype(np.float64)
    return X,np.asarray(vectorizer.get_feature_names_out())


def artm_plsa(X: csr_matrix, topics: int = 7, iterations: int=30,
              alpha: float=-.18,beta:float=-.07,decorrelation_ratio:float=.025,seed:int=42):
    """Generic ARTM M-step for log smoothing/sparsity and topic decorrelation.

    For C_{dw} token counts, q_{dwt} proportional theta_{dt} * phi_{wt}.
    The regularizer R = alpha*sum(log theta) + beta*sum(log phi)
          - tau/2 * sum_{w,t != s}(phi[w,t]*phi[w,s]).
    The corresponding generalized EM M-step uses expected counts plus
    theta*dR/dtheta and phi*dR/dphi, clipped to the simplex.
    This is a controlled subset of the ARTM family, not the ITAR algorithm.
    """
    rng=np.random.default_rng(seed)
    D,V=X.shape
    K=min(topics,V-1,max(2,D//20))
    theta=rng.dirichlet(np.full(K,.65),size=D)
    phi=rng.dirichlet(np.full(V,.55),size=K).T
    coo=X.tocoo()
    d=coo.row.astype(np.int32);w=coo.col.astype(np.int32)
    weights=coo.data.astype(np.float64)
    tau=decorrelation_ratio*float(weights.sum())
    for _ in range(iterations):
        logits=theta[d,:]*phi[w,:]
        post=logits/np.maximum(logits.sum(axis=1,keepdims=True),1e-20)
        post*=weights[:,None]
        n_dt=np.column_stack([np.bincount(d,weights=post[:,t],minlength=D) for t in range(K)])
        n_wt=np.column_stack([np.bincount(w,weights=post[:,t],minlength=V) for t in range(K)])
        theta=np.maximum(n_dt+alpha,1e-15)
        theta/=theta.sum(axis=1,keepdims=True)
        cross=phi.sum(axis=1,keepdims=True)-phi
        phi=np.maximum(n_wt+beta-tau*phi*cross,1e-15)
        phi/=phi.sum(axis=0,keepdims=True)
    return theta,phi


def npmi_top_words(X: csr_matrix, phi: np.ndarray, top_k:int=8) -> list[float]:
    """Document-based NPMI with zero pairs scored -1; exploratory metric."""
    n_docs=X.shape[0]
    binary=X.copy();binary.data[:]=1
    output=[]
    for k in range(phi.shape[1]):
        words=np.argsort(phi[:,k])[-top_k:]
        B=binary[:,words].toarray().astype(np.float32)
        freq=B.sum(axis=0)
        together=B.T@B
        values=[]
        for i in range(len(words)):
            for j in range(i+1,len(words)):
                c=together[i,j]
                if c<=0:values.append(-1.0);continue
                px=max(float(freq[i])/n_docs,1e-12)
                py=max(float(freq[j])/n_docs,1e-12)
                pxy=max(float(c)/n_docs,1e-12)
                values.append(float(np.log(pxy/(px*py))/-np.log(pxy)) if pxy<1 else 0.)
        output.append(float(np.mean(values)) if values else 0.0)
    return output


def as_topics(theta,phi,vocab,rows,coherence,label:str):
    K=phi.shape[1]
    top_words=[list(map(str,vocab[np.argsort(phi[:,k])[-12:][::-1]])) for k in range(K)]
    by_topic=[]
    for k in range(K):
        months: dict[str,list[float]]=defaultdict(list)
        for i,r in enumerate(rows):
            months[r['date'][:7]].append(float(theta[i,k]))
        examples=[]
        for idx in np.argsort(theta[:,k])[::-1][:3]:
            row=rows[int(idx)]
            examples.append({'id':row['id'],'date':row['date'],'title':row.get('title') or 'Публикация',
                             'url':row.get('url',''),'attribution':row.get('attribution','')})
        by_topic.append({'id':f'{label}_{k+1}','keywords':top_words[k],
                         'proportion':float(theta[:,k].mean()),
                         'coherence':float(coherence[k]),
                         'by_month':{m:round(float(np.mean(v)),6) for m,v in sorted(months.items())},
                         'examples':examples})
    diversity=len(set(word for group in top_words for word in group[:10]))/(K*10)
    return by_topic,round(float(diversity),4)


def build_models(data_dir:Path,out_path:Path,max_docs_per_leader:int=1400,topics:int=7,iterations:int=30):
    result={'schema_version':1,'status':'experimental','year':2026,
       'method':'Регуляризованная PLSA (ARTM-подход) + NMF (контрольная модель)',
       'created_at':datetime.now(timezone.utc).strftime('%Y-%m-%d UTC'),
       'limitations':['Не используется BigARTM / ITAR; реализована лишь часть семейства ARTM',
                      'Темы по языкам не выровнены; сравнение тем между лидерами запрещено без дополнительной проверки',
                      'Исследовательские корпуса имеют неполное покрытие и различные виды текстов',
                      'Темы не прошли экспертную разметку; NPMI и разнообразие — автоматические индикаторы'],
       'papers':[{'name':'Воронцов, Потапенко, 2012','url':'https://crm.ics.org.ru/uploads/crmissues/crm_2012_4/12403.pdf'},
                 {'name':'Веселова, Воронцов, 2020','url':'https://aclanthology.org/2020.acl-srw.9.pdf'},
                 {'name':'Горбулев, Алексеев, Воронцов, 2024 (ITAR)','url':'https://arxiv.org/pdf/2408.05840'}],
       'leaders':{}}
    for leader,name in LEADERS.items():
        source_rows=list(read_jsonl(data_dir/f'{leader}.jsonl',leader).values())
        source_rows=[r for r in source_rows if len(r.get('text','').split())>=8]
        if len(source_rows)<60:
            result['leaders'][leader]={'status':'insufficient_data','documents':len(source_rows),'topics':[]}
            continue
        rows=stratified_subset(source_rows,max_docs_per_leader)
        language=safe_tokenizer_language(leader)
        X,vocab=token_matrix(rows,language)
        # English-only Telegram posts are not Ukrainian discourse; likewise for
        # other languages. Retain only documents with usable native-script terms.
        keep=np.asarray((X>0).sum(axis=1)).ravel()>=3
        X=X[keep,:]
        rows=[row for row,ok in zip(rows,keep) if ok]
        if len(rows)<50 or X.shape[1]<topics+3:
            raise ValueError('Vocabulary or original-language sample too small for '+leader)
        model_K=min(topics, max(2,int(X.shape[1]/10)))
        theta,phi=artm_plsa(X,topics=model_K,iterations=iterations)
        coh=npmi_top_words(X,phi)
        built,diversity=as_topics(theta,phi,vocab,rows,coh,'artm')
        # Control nonprobabilistic model, not a substitute for ITAR.
        tfidf=TfidfTransformer(sublinear_tf=True).fit_transform(X)
        baseline=NMF(n_components=model_K,init='nndsvda',random_state=42,max_iter=240,
                     alpha_W=.01,alpha_H=.01,l1_ratio=.2)
        w=baseline.fit_transform(tfidf)
        h=baseline.components_.T
        norm=w/np.maximum(w.sum(axis=1,keepdims=True),1e-12)
        pm=h/np.maximum(h.sum(axis=0,keepdims=True),1e-12)
        control_coh=npmi_top_words(X,pm)
        result['leaders'][leader]={
          'status':'experimental','language':language,'documents':len(source_rows),
          'sample_documents':len(rows),'vocabulary_size':len(vocab),
          'topics':built,'method':'regularized_plsa_sparse_decorrelation',
          'quality':{'npmi_mean':round(float(np.mean(coh)),4),'topic_diversity_10':diversity,
                     'negative_npmi_topics':sum(x<0 for x in coh),
                     'nmf_npmi_mean':round(float(np.mean(control_coh)),4),
                     'nmf_reconstruction_error':round(float(baseline.reconstruction_err_),4)},
          'attribution_note':('Тексты пресс-службы Кремля, не персональная речь Путина' if leader=='putin' else
                              'Посты Telegram, авторство отдельных сообщений не подтверждено' if leader=='zelenskyy' else
                              'Вторичный архив Truth Social'),
          'source_documents':dict(Counter(r['source'] for r in source_rows))
        }
    out_path.parent.mkdir(parents=True,exist_ok=True)
    out_path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--data-dir',default='data/2026');p.add_argument('--out',default='docs/data/topics.json')
    p.add_argument('--max-docs',type=int,default=1400);p.add_argument('--topics',type=int,default=7)
    p.add_argument('--iterations',type=int,default=30)
    a=p.parse_args()
    r=build_models(Path(a.data_dir),Path(a.out),a.max_docs,a.topics,a.iterations)
    for leader,info in r['leaders'].items():
        print(leader,info.get('status'),info.get('sample_documents'),info.get('quality'))

if __name__=='__main__':main()
