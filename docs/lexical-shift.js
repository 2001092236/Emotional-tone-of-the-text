/* Статистический сдвиг словаря внутри одного языкового корпуса.
 * Вдохновлено Monroe, Colaresi & Quinn (2008): log-odds with a pooled
 * empirical Dirichlet prior, z-нормировка; не сравнительный рейтинг политиков.
 * Ни один запрос не отправляется на сервер: расчёт работает локально в браузере.
 */
(function (root) {
  'use strict';
  const stop = {
    en: new Set('about after again against also among and are because been before being between both but can could did does doing down each even every for from had has have here how into its just like many more most much must not now only other our out over same she should some such than that the their them there these they this those through too under until very was were what when where which while who why will with would you your www http https com html twitter president truth social'.split(' ')),
    ru: new Set('авто без был была было были быть вам вас ваш ваши весь вот все всех всей весь где для его ее ещё или как когда кого конечно лишь мне мой мы нам нас наш нет они она оно опять уже они тоже после при про сами себе свой своих тебя тебя там так также того тогда того тут хоть чего чем через это этой этого этих который которая которое которые какими сегодня есть здесь мне вам нас вам это наш вам'.split(' ')),
    uk: new Set('або але був була було були бути вам вас ваш вона вони воно від він для його її їм їх вже звідси є ще знову його іще якщо інший інші колись коли кому крім між мене ми мій моя моє мої нам нас наша наші нею них ніхто нині ними один одна одного однак отже перед після при про разом себе свій свого свої також там тебе те це цей ця цьому цих чи щоб як які який яка яких якщо сьогодні тут'.split(' '))
  };
  function parse(text, lang) {
    const cleaned = String(text || '').replace(/https?:\/\/\S+/ig,' ').replace(/(?:www\.)\S+/ig,' ').toLowerCase();
    const pattern = lang === 'en' ? /\b[a-z]{4,}\b/g : lang === 'ru' ? /[а-яё]{4,}/g : /[а-яіїєґ]{4,}/g;
    return (cleaned.match(pattern) || []).filter(w => !stop[lang].has(w));
  }
  function logodds(left, right, lang, minCount=12) {
    const ca = new Map(), cb = new Map();let na=0,nb=0;
    for (const d of left) for (const w of parse(d.text,lang)){ca.set(w,(ca.get(w)||0)+1);na++;}
    for (const d of right) for (const w of parse(d.text,lang)){cb.set(w,(cb.get(w)||0)+1);nb++;}
    const vocab = new Set([...ca.keys(),...cb.keys()]);
    const alpha = w => .1 + .01*((ca.get(w)||0)+(cb.get(w)||0));
    let alpha0=0;for(const w of vocab)alpha0+=alpha(w);
    const rows=[];
    for(const w of vocab){const a=ca.get(w)||0,b=cb.get(w)||0;
      if(a+b<minCount)continue;
      const p=alpha(w);
      const den1=na+alpha0-a-p,den2=nb+alpha0-b-p;
      if(den1<=0||den2<=0)continue;
      const delta=Math.log((b+p)/den2)-Math.log((a+p)/den1);
      const variance=1/(a+p)+1/(b+p);
      const z=delta/Math.sqrt(variance);
      if(Number.isFinite(z)) rows.push({word:w,z:+z.toFixed(3),early:a,late:b,rateEarly:na?+(a*10000/na).toFixed(1):0,rateLate:nb?+(b*10000/nb).toFixed(1):0});
    }
    rows.sort((a,b)=>b.z-a.z);
    return {earlyTokens:na,lateTokens:nb,increase:rows.filter(r=>r.z>0).slice(0,8),decrease:rows.filter(r=>r.z<0).reverse().slice(0,8),vocabulary:vocab.size};
  }
  function compare(docs,leader,start,end) {
    if(!['trump','putin','zelenskyy'].includes(leader))return {status:'select_person'};
    if(!start||!end||start>end)return {status:'invalid_range'};
    const days=Math.floor((Date.parse(end+'T00:00:00Z')-Date.parse(start+'T00:00:00Z'))/86400000)+1;
    if(days<14)return {status:'too_short',days};
    const mid=new Date((Date.parse(start+'T00:00:00Z')+Date.parse(end+'T00:00:00Z'))/2).toISOString().slice(0,10);
    const lang={trump:'en',putin:'ru',zelenskyy:'uk'}[leader];
    const filtered=docs.filter(d=>d.leader===leader&&d.date>=start&&d.date<=end);
    const early=filtered.filter(d=>d.date<=mid),late=filtered.filter(d=>d.date>mid);
    if(early.length<12||late.length<12)return {status:'not_enough',earlyDocuments:early.length,lateDocuments:late.length,mid};
    const computed=logodds(early,late,lang);
    if(computed.earlyTokens<1000||computed.lateTokens<1000)return {status:'not_enough_tokens',...computed};
    return {status:'ok',leader,language:lang,mid,earlyFrom:start,earlyUntil:mid,lateFrom:new Date(Date.parse(mid+'T00:00:00Z')+86400000).toISOString().slice(0,10),lateUntil:end,earlyDocuments:early.length,lateDocuments:late.length,...computed};
  }
  const api={compare,logodds,parse};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  root.LexicalShift=api;
})(typeof window !== 'undefined'?window:globalThis);
