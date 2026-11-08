'use strict';
const $=id=>document.getElementById(id), fmt=n=>Number(n||0).toLocaleString('ru-RU');
const node=(tag,text,cl)=>{const n=document.createElement(tag);if(cl)n.className=cl;if(text!==undefined)n.textContent=text;return n;};
const NAMES={trump:'Трамп · Truth Social',putin:'Пресс-служба Кремля · Telegram',zelenskyy:'Зеленский · Telegram'};
let current='trump',report=null;
function render(){const d=report?.leaders?.[current];if(!d||d.status!=='experimental'){$('itarStatus').textContent='Для этого корпуса нет проверенного модельного эксперимента.';return;}
$('itarStatus').textContent='Эксперимент выполнен: '+report.created_at+'. Язык: '+d.language+'. Исходный материал: '+NAMES[current]+'. Итерации не равны месяцам.';
$('itarDocs').textContent=fmt(d.sample_documents);$('itarStability').textContent=Number(d.baseline_stability_mean).toFixed(2);
$('itarTopicsN').textContent=fmt(d.good_topics_accumulated);
const rounds=$('itarLineage');rounds.replaceChildren();for(const [i,step] of d.rounds.entries()){if(i)rounds.append(node('span','→','itar-arrow'));const card=node('div',undefined,'itar-round');card.append(node('small','Раунд '+step.round),node('strong',step.accepted_total),node('small','Добавлено: '+step.accepted_added));rounds.append(card);}
$('itarThreshold').textContent='Автоматические пороги на этом языковом корпусе: NPMI хороших тем ≥ '+Number(d.good_threshold_npmi).toFixed(3)+'; плохих ≤ '+Number(d.bad_threshold_npmi).toFixed(3)+'. Базовая модель (лучшая из инициализаций): средняя NPMI '+Number(d.baseline_best_mean_npmi).toFixed(3)+'. Это не строгая внешняя оценка ITAR.';
const cards=$('itarTopicCards');cards.replaceChildren();for(const t of d.topics||[]){const el=node('article',undefined,'itar-topic');el.append(node('h3','Тема '+String(t.id).replace(/\D/g,'')),node('p',t.keywords.slice(0,10).join(' · ')),node('small','Принята на раунде '+t.accepted_round+' · NPMI '+Number(t.coherence).toFixed(3)));cards.append(el);}if(!cards.children.length)cards.append(node('p','Автоматический порог не пропустил тем. Это диагностический результат, а не ошибка.'));
$('itarSource').textContent='Дата: '+d.sample_date_min+' — '+d.sample_date_max+' · SHA-256 корпуса: '+d.source_jsonl_sha256.slice(0,20)+'… · Темы не прошли экспертной разметки.';
}
for(const button of document.querySelectorAll('[data-leader]')){button.addEventListener('click',()=>{current=button.dataset.leader;for(const b of document.querySelectorAll('[data-leader]'))b.setAttribute('aria-pressed',String(b===button));render();});}
fetch('data/itar_experiment.json',{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('исследование ещё не запускалось');return r.json()}).then(d=>{if(d.schema_version!==1||d.year!==2026)throw Error('неподдерживаемая версия');report=d;render()}).catch(e=>{$('itarStatus').textContent='Результаты пока отсутствуют: '+e.message+'; статические иллюстративные числа не показываются.';});
