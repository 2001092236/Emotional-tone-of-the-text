'use strict';
const $=id=>document.getElementById(id);
const MN=['Янв','Фев','Мар','Апр','Май','Июн','Июл','Авг','Сен','Окт','Ноя'];
const add=(tag,text,cl)=>{const e=document.createElement(tag);if(cl)e.className=cl;if(text!==undefined)e.textContent=text;return e;};
const fmt=n=>Number(n||0).toLocaleString('ru-RU');
let records=[];
let licensedTextsPromise=null;
async function licensedTextById(id){
 if(!licensedTextsPromise){
   licensedTextsPromise=fetch('data/hf_speeches_full_2026.json',{cache:'no-store'})
     .then(r=>{if(!r.ok)throw Error('файл полных копий ещё не опубликован');return r.json()})
     .then(data=>{if(data.schema_version!==1||!Array.isArray(data.documents))throw Error('неожиданный формат');return new Map(data.documents.map(d=>[d.id,d]));});
 }
 return (await licensedTextsPromise).get(id);
}
function readingPanel(record){
 const details=add('details',undefined,'licensed-reader');
 details.append(add('summary','Читать полную неизменённую копию'));
 details.addEventListener('toggle',async()=>{
   if(!details.open||details.dataset.ready)return;
   details.dataset.ready='1';
   const textNode=add('pre','Читаем текст…');
   details.append(textNode);
   try{
     const full=await licensedTextById(record.id);
     if(!full||!full.text)throw Error('для этой записи полная копия не включена');
     textNode.textContent=full.text;
     const footer=add('div','Источник: '+full.rights_holder_credit+' · архив Hugging Face · CC BY-NC-ND 4.0. Копия из HF сохранена без изменений; совпадение с оригиналом не удостоверено.','licensed-footer');
     const a=add('a','Условия лицензии');a.href=full.original_material_license_url;a.target='_blank';a.rel='noopener noreferrer';footer.append(a);
     details.append(footer);
   }catch(err){textNode.textContent='Полный текст пока недоступен: '+err.message+'. Открой ссылку на первоисточник выше.';}
 });
 return details;
}
function renderIndex(){const lang=$('speechLang').value,month=$('speechMonth').value,q=$('speechQuery').value.toLocaleLowerCase('ru');const found=records.filter(r=>(lang==='all'||lang===r.language)&&(month==='all'||r.date.slice(0,7)===month)&&(!q||r.title.toLocaleLowerCase('ru').includes(q)));
$('speechFound').textContent=fmt(found.length)+' записей соответствуют фильтрам. Отображены первые 100.';const list=$('speechList');list.replaceChildren();for(const r of found.slice(0,100)){const item=add('div',undefined,'speech-record'),left=add('div'),link=add('a',r.title||'Выступление');link.href=r.url;link.target='_blank';link.rel='noopener noreferrer';left.append(link,add('small',r.date+' · '+(r.language==='uk'?'Украинский оригинал':'Английский перевод')+' · '+fmt(r.word_count)+' слов · контрольная сумма: '+r.text_sha256.slice(0,12)));left.append(readingPanel(r));item.append(left,add('small','Первоисточник ↗'));list.append(item);}if(!found.length)list.append(add('p','Нет публикаций в этой части доступного архива.'));
}
async function start(){try{const [sr,ir,tr]=await Promise.all([fetch('data/hf_speeches_2026.json',{cache:'no-store'}),fetch('data/hf_speeches_index.json',{cache:'no-store'}),fetch('data/hf_official_topics.json',{cache:'no-store'})]);if(!sr.ok||!ir.ok||!tr.ok)throw Error('Отчёт импорта ещё не создан в GitHub Actions.');const s=await sr.json(),list=await ir.json(),model=await tr.json();if(s.schema_version!==1||!Array.isArray(list))throw Error('Некорректная версия архива');records=list.sort((a,b)=>b.date.localeCompare(a.date));$('speechTotal').textContent=fmt(s.total_2026_speeches);$('speechUK').textContent=fmt(s.original_uk);$('speechLast').textContent=s.latest||'—';$('speechCoverage').textContent='Границы найденного архива: '+(s.earliest||'—')+' — '+(s.latest||'—')+'. Все отсутствующие даты требуют внешней сверки.';
$('speechStatus').textContent='Выполнен однократный исследовательский импорт. Ссылки и метаданные опубликованы; для опубликованных неизменённых исследовательских копий доступно чтение прямо в карточке речи.';
for(let i=1;i<=11;i++){const key='2026-'+String(i).padStart(2,'0'),n=(s.by_month||{})[key]||0,cell=add('div',undefined,'speech-month');cell.append(add('small',MN[i-1]),add('strong',n?fmt(n):'—'));cell.title=key+': '+fmt(n)+' текстов в доступной копии';$('speechMonths').append(cell);const o=add('option',key);o.value=key;$('speechMonth').append(o);}
const tbox=$('speechTopics');const t=model.original_speeches||{};if(t.status==='experimental'){for(const theme of (t.topics||[]).slice(0,7)){const card=add('div',undefined,'speech-topic');card.append(add('h3','Тема '+String(theme.id||'').replace(/\D/g,'')),add('p',(theme.keywords||[]).slice(0,9).join(' · ')),add('small','NPMI: '+Number(theme.coherence||0).toFixed(2)+' · доля: '+Math.round(100*(theme.proportion||0))+'%'));tbox.append(card);}}else tbox.append(add('p','Недостаточно украинских оригиналов для достоверного тематического эксперимента.'));
fetch('data/hf_official_itar.json',{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('ITAR ещё не рассчитан');return r.json()}).then(payload=>{const z=payload.original_speeches||{};const wrap=$('speechItar');wrap.replaceChildren();if(z.status==='experimental'){for(const t of z.topics||[]){const card=add('div',undefined,'speech-topic');card.append(add('h3','Тема '+String(t.id).replace(/\D/g,'')),add('p',(t.keywords||[]).slice(0,8).join(' · ')),add('small','NPMI '+Number(t.coherence).toFixed(3)+' · итерация '+t.accepted_round));wrap.append(card);}$('speechItarNote').textContent='В обучении: '+fmt(z.documents)+' речей. Сходство независимых инициализаций: '+Number(z.baseline_stability_mean).toFixed(2)+'. Принято тем: '+fmt(z.good_topics_accumulated)+'. Модель предварительная, экспертами не подтверждена.';}else {$('speechItarNote').textContent='Для ITAR недостаточно оригинальных речей в текущей выборке.';}}).catch(err=>{$('speechItarNote').textContent='Эксперимент ITAR: '+err.message;});
for(const id of ['speechLang','speechMonth','speechQuery'])$(id).addEventListener(id==='speechQuery'?'input':'change',renderIndex);renderIndex();
}catch(err){$('speechStatus').textContent='Официальные речи пока не импортированы: '+err.message;$('speechTopics').append(add('p','Результаты не выдумываются: требуется запуск чтения разрешённого источника.'));}}
start();
