'use strict';
const $=id=>document.getElementById(id);
const fmt=n=>Number(n||0).toLocaleString('ru-RU');
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
async function start(){
  try{
    const [a,b]=await Promise.all([
      fetch('data/hf_putin_probe.json',{cache:'no-store'}),
      fetch('data/hf_putin_speeches_index.json',{cache:'no-store'})]);
    if(!a.ok||!b.ok)throw new Error('исследовательская проверка ещё не была выполнена');
    const meta=await a.json(),list=await b.json();
    if(meta.year!==2026||!Array.isArray(list))throw Error('неподдерживаемый формат отчёта');
    $('putinCount').textContent=fmt(meta.matching_russian_putin_speeches);
    $('putinFirst').textContent=meta.earliest||'—';$('putinLast').textContent=meta.latest||'—';
    const count=meta.matching_russian_putin_speeches;
    if(count){$('putinStatus').textContent='В исследовательском архиве обнаружено '+fmt(count)+' русскоязычных записей 2026 года. Полнота не проверена; требуется сверка с официальным источником.';}
    else {$('putinStatus').textContent='Речи за 2026 год в проверенной части научной копии не подтверждены. Это НЕ означает, что таких речей не было.';}
    if(meta.errors?.length){$('putinStatus').textContent+=' Ограничения проверки: '+meta.errors.slice(0,2).join('; ');}
    const root=$('putinList');root.replaceChildren();
    for(const r of list.slice(0,80)){
      const entry=el('article',undefined,'putin-entry'),link=el('a',r.title||'Оригинальный источник');
      link.href=r.source_url;link.target='_blank';link.rel='noopener noreferrer';
      entry.append(link,el('small',`${r.date} · ${fmt(r.word_count)} слов · ID SHA256 ${String(r.text_sha256).slice(0,12)}`));root.append(entry);
    }
    if(!list.length)root.append(el('p','Пока нет подтверждённых документов в этой выборке.'));
  }catch(e){$('putinStatus').textContent='Отчёт ещё недоступен: '+e.message;}
}
start();
