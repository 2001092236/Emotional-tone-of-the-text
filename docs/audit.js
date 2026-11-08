/* Прозрачный аудит: только фактические цифры из docs/data/audit.json. */
'use strict';
const AUDIT_NAMES={trump:'Дональд Трамп',putin:'Владимир Путин',zelenskyy:'Владимир Зеленский'};
const MONTH_NAMES=['Янв','Фев','Мар','Апр','Май','Июн','Июл','Авг','Сен','Окт','Ноя','Дек'];
let AUDIT_DATA=null;
const byId=(id)=>document.getElementById(id);
function add(tag,cls,txt){const n=document.createElement(tag);if(cls)n.className=cls;if(txt!==undefined)n.textContent=txt;return n;}
function format(n){return Number(n||0).toLocaleString('ru-RU');}
function renderAudit(){
 const wrap=byId('auditCards');wrap.replaceChildren();if(!AUDIT_DATA)return;
 const leader=byId('auditLeader').value;
 for(const [id,item] of Object.entries(AUDIT_DATA.sources||{})){
   if(leader!=='all'&&item.leader!==leader)continue;
   const card=add('section','audit-card');
   const head=add('div','audit-card-head'),left=add('div');
   left.append(add('div','small-overline',AUDIT_NAMES[item.leader]||item.leader),add('h2',null,item.kind));
   left.append(add('p',null,item.attribution));
   head.append(left,add('div','audit-n',format(item.observed)));card.append(head);
   const range=add('div','audit-interval',item.first_date?('Наблюдаемые даты: '+item.first_date+' — '+item.last_date):'Не удалось получить ни одного текста.');card.append(range);
   card.append(add('div','audit-month-label','СОХРАНЁННЫЕ ДОКУМЕНТЫ ПО МЕСЯЦАМ'));
   const months=add('div','audit-months');
   for(const [month,n] of Object.entries(item.by_month||{})){
     const cell=add('div','audit-month '+(n?'has':'empty'));
     cell.title=month+': '+(n?format(n)+' найденных записей':'в архиве нет записей');
     cell.append(add('b',null,n?format(n):'—'),add('span',null,MONTH_NAMES[Number(month.slice(5,7))-1]));months.append(cell);
   }
   card.append(months);
   const gap=item.largest_unobserved_interval;
   if(gap?.days>0){card.append(add('div','audit-signal',
     'Наибольший интервал без обнаруженных записей: '+gap.days+' дн. ('+gap.start+' — '+gap.end+'). Не равно отсутствию публикаций.'));}
   if(item.ingestion_status_initial==='error'){card.append(add('p',null,'Первичная загрузка источника завершилась ошибкой.'));}
   wrap.append(card);
 }
 if(!wrap.children.length)wrap.append(add('div','empty-state','Нет источников в выбранной группе.'));
}
async function init(){
 byId('auditLeader').addEventListener('change',renderAudit);
 try{
   const resp=await fetch('data/audit.json',{cache:'no-store'});
   if(!resp.ok)throw Error('HTTP '+resp.status);
   const data=await resp.json();
   if(data.schema_version!==1||data.window?.since!=='2026-01-01')throw Error('Неподдерживаемая версия аудита');
   AUDIT_DATA=data;
   byId('auditN').textContent=format(data.total_observed);
   byId('auditSources').textContent=format(Object.values(data.sources||{}).filter(v=>v.observed>0).length);
   byId('auditComplete').textContent=data.completeness_verified?'Подтверждено':'Не проверено';
   byId('auditStatus').textContent='Срез: '+data.window.since+' — '+data.window.until+'. '+data.not_complete_reason;
   renderAudit();
 }catch(err){byId('auditStatus').textContent='Аудит ещё не рассчитан или не опубликован: '+err.message;}
}
init();
