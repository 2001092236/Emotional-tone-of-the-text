const $ = (id) => document.getElementById(id);
const names = {trump:'Дональд Трамп',putin:'Владимир Путин',zelenskyy:'Владимир Зеленский'};
const shortNames={trump:'Трамп',putin:'Путин',zelenskyy:'Зеленский'};
const mNames=['Янв','Фев','Мар','Апр','Май','Июн','Июл','Авг','Сен','Окт','Ноя','Дек'];
let summary={files:{},by_month:{},by_leader:{},total:0,words:0}, loaded=[], shown=0, matching=[];
function fmt(n){return Number(n||0).toLocaleString('ru-RU')}
function elem(tag,cls,text){const el=document.createElement(tag); if(cls) el.className=cls; if(text!==undefined) el.textContent=text; return el}
function chooseMonths(){const select=$('month'); const all=elem('option',null,'Все месяцы 2026');all.value='all';select.replaceChildren(all);
 for(let m=1;m<=12;m++){const opt=elem('option',null,`${mNames[m-1]} 2026`);opt.value='2026-'+String(m).padStart(2,'0');select.append(opt)} }
function dashboard(){
 $('total').textContent=fmt(summary.total);$('words').textContent=fmt(summary.words);
 $('coverage').textContent=summary.coverage_verified?'Проверено':'Не проверено';
 const buckets=[];for(let m=1;m<=12;m++){const key='2026-'+String(m).padStart(2,'0');let value=0;for(const name of Object.keys(names))value+=(summary.by_month[name]||{})[key]||0;buckets.push({key,value})}
 const max=Math.max(1,...buckets.map(d=>d.value));$('timeline').replaceChildren();
 for(let i=0;i<12;i++){const b=buckets[i],box=elem('div','monthBar');box.title=`${mNames[i]}: ${b.value}`;box.append(elem('small',null,b.value?fmt(b.value):''));const bar=elem('div');bar.style.height=(b.value?Math.max(3,120*b.value/max):0)+'px';box.append(bar,elem('span',null,mNames[i]));$('timeline').append(box)}
 $('sources').replaceChildren();for(const [key,value] of Object.entries(names)){const x=elem('div','source'),left=elem('div');left.append(elem('strong',null,value));left.append(elem('div','meta',key==='trump'?'Truth Social — вторичный архив':key==='putin'?'kremlin.ru — стенограммы; Telegram — пресс-служба':'president.gov.ua — выступления; Telegram — посты'));x.append(left,elem('div','n',fmt(summary.by_leader[key]||0)));$('sources').append(x)}
 if(summary.last_run?.sources){for(const [name,item] of Object.entries(summary.last_run.sources)){const note=elem('div','meta',`${shortNames[name]}: ${item.status}${item.error?' — '+item.error:''}`);$('sources').append(note)}}
}
async function loadSelection(){const key=$('leader').value,month=$('month').value;const people=key==='all'?Object.keys(names):[key];const months=month==='all'?Array.from({length:12},(_,i)=>'2026-'+String(i+1).padStart(2,'0')):[month];const files=[];
 for(const name of people)for(const m of months){const path=summary.files[`${name}:${m}`];if(path)files.push('data/'+path)}
 $('status').textContent=files.length?'Загружаю архивные документы…':(summary.total?'Для выбранного периода записей нет.':'Годовой архив ещё не загружен. Запусти историческую выгрузку в GitHub Actions.');
 try{const data=await Promise.all(files.map(async f=>{const r=await fetch(f,{cache:'no-store'});if(!r.ok)throw Error(`${r.status} ${f}`);return r.json()}));loaded=data.flat();loaded.sort((a,b)=>b.date.localeCompare(a.date));$('status').textContent=`Загружено ${fmt(loaded.length)} документов по выбранным фильтрам. Полнота архива не подтверждена.`;applyFilters()}catch(err){$('status').textContent=`Не удалось загрузить документы: ${err.message}`;$('documents').replaceChildren();$('matches').textContent='Ошибка'}
}
function applyFilters(){const q=$('search').value.trim().toLocaleLowerCase('ru');const att=$('attribution').value;
 matching=loaded.filter(d=>{const a=d.attribution||''; if(att==='direct'&&!['official_speech_text','direct_speech_segment'].includes(a))return false;if(att==='other'&&['official_speech_text','direct_speech_segment'].includes(a))return false;return !q||[d.title,d.text,d.source].join(' ').toLocaleLowerCase('ru').includes(q)});
 shown=0;$('documents').replaceChildren();$('matches').textContent=`${fmt(matching.length)} результатов`;more()}
function more(){const list=$('documents');const part=matching.slice(shown,shown+40);shown+=part.length;
 for(const d of part){const item=elem('details','doc');const top=elem('summary');const meta=elem('div','docMeta',`${names[d.leader]}  ·  ${d.date}  ·  ${d.source}`);top.append(meta,elem('h3',null,d.title||'(Без заголовка)'));const tags=elem('div','tags');for(const label of [d.genre,d.attribution,d.language,`${fmt(d.word_count)} слов`])tags.append(elem('span','tag',label));top.append(tags);item.append(top,elem('div','docText',d.text||''));
 if(d.url){const link=elem('a',null,'Перейти к первоисточнику');link.href=d.url;link.target='_blank';link.rel='noopener noreferrer';item.append(link)}list.append(item)}
 $('more').hidden=shown>=matching.length}
async function start(){chooseMonths();$('month').value='all';try{const response=await fetch('data/summary.json',{cache:'no-store'});if(!response.ok)throw Error('HTTP '+response.status);summary=await response.json();dashboard();await loadSelection()}catch(e){$('status').textContent='Публикация ещё не содержит данных корпуса: '+e.message}}
 $('leader').addEventListener('change',loadSelection);$('month').addEventListener('change',loadSelection);$('search').addEventListener('input',applyFilters);$('attribution').addEventListener('change',applyFilters);$('more').addEventListener('click',more)}
start();
