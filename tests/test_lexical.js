'use strict';
const assert = require('node:assert/strict');
const {compare, parse}=require('../docs/lexical-shift.js');
assert.deepEqual(parse('https://foo.com/secret and America economy election','en'),['america','economy','election']);
const docs=[];
function doc(day,text){return {leader:'trump',date:`2026-0${day<=28?'1':'8'}-${String(day<=28?day:day-28).padStart(2,'0')}`,text};}
for(let i=1;i<=24;i++)docs.push(doc(i, 'senate senate senate legislation budget economy tax jobs security and america people '.repeat(12)));
for(let i=29;i<=52;i++)docs.push(doc(i, 'diplomacy diplomacy diplomacy ceasefire negotiation agreement summit international policy america people '.repeat(12)));
const res=compare(docs,'trump','2026-01-01','2026-08-24');
assert.equal(res.status,'ok');
assert(res.increase.some(w=>w.word==='diplomacy'));
assert(res.decrease.some(w=>w.word==='senate'));
assert.equal(compare(docs,'all','2026-01-01','2026-08-24').status,'select_person');
assert.equal(compare(docs,'trump','2026-01-01','2026-01-04').status,'too_short');
console.log('4 lexical shift checks passed');
