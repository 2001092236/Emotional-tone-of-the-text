import numpy as np
from scipy.sparse import csr_matrix
from corpus2026.itar import aligned_similarity,train_with_history,learn_topic_history

def synthetic():
    rng=np.random.default_rng(17)
    x=np.zeros((100,34),dtype=np.float64)
    for i in range(100):
        topic=i%4
        for j in range(5):
            x[i,topic*8+j]=rng.integers(2,5)
        x[i,32:34]=rng.integers(1,3,size=2)
    return csr_matrix(x),np.asarray([f'w{i}' for i in range(34)])

def test_topic_alignment_permutation_invariant():
    a=np.array([[.9,.1,0],[.1,.9,0],[0,0,1.]])
    b=a[:,[2,0,1]]
    assert abs(aligned_similarity(a,b)-1)<1e-9

def test_fixed_topic_is_preserved_and_normalized():
    X,v=synthetic()
    fixed=np.zeros(X.shape[1]);fixed[:7]=1/7
    theta,phi=train_with_history(X,4,5,42,[fixed],[],hard_fix=True)
    assert phi.shape==(X.shape[1],4)
    assert theta.shape==(X.shape[0],4)
    assert np.allclose(phi[:,0],fixed,atol=1e-10)
    assert np.allclose(phi.sum(axis=0),1)
    assert np.allclose(theta.sum(axis=1),1)

def test_itar_monotone_and_has_provenance():
    X,words=synthetic()
    r=learn_topic_history(X,words,K=4,iterations=8,rounds=3,seeds=(11,17))
    values=[x['accepted_total'] for x in r['rounds']]
    assert values==sorted(values)
    assert 0<=r['baseline_stability_mean']<=1.00001
    assert r['good_topics_accumulated']==len(r['topics'])
    assert all(t['coherence']>=0 for t in r['topics'])
    assert all(len(t['keywords'])>=5 for t in r['topics'])
    assert r['replica_of_authors_code'] is False
