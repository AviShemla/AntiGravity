"""Standalone proposal + pure S08 selection computation; never authorization."""
from __future__ import annotations
from dataclasses import asdict,dataclass,replace
from datetime import date
import hashlib,json,math,struct
from types import MappingProxyType
from typing import Iterable,Mapping,Sequence

__all__=("SignalPanel","Lineage","Evidence","CompleteRunResult","SCIENTIFIC_CONTRACT_BYTES",
         "build_signal_panel","audit_signal_panel","evaluate_candidate","audit_evidence",
         "select_complete_run","audit_complete_run_result")
_OUTER=((1,0,288,289,295,296,325),(2,30,318,319,325,326,355),(3,60,348,349,355,356,385),(4,90,378,379,385,386,415))
_INNER=((1,0,132,133,139,140,191),(2,0,184,185,191,192,243),(3,0,236,237,243,244,288))
_TOTAL=6_277_656;_PER_FOLD=1_569_414;_GROUP=3311;_GROUPS=1896;_MAX=9480
_PANEL_CONTRACT="S08_FROZEN_TURSO_SPLIT_ADJUSTED_RETURN_PANEL_V1"
_REQUIRED_EXTERNAL_IDENTITIES=("dataset_version","snapshot_sha256","frozen_dataset_sha256","frozen_content_sha256","readback_sha256","calendar_sha256","signal_panel_sha256","preregistration_sha256","policy_sha256","selector_code_sha256","selector_release_sha256","dependency_closure_sha256","materializer_release_sha256","materializer_evidence_sha256","independent_review_event_sha256")
def _cj(x):return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode()
def _sha(x):return hashlib.sha256(x).hexdigest()
SCIENTIFIC_CONTRACT_BYTES=_cj({"contract":"S08_NESTED_PREDICTIVE_SELECTION_V7","scope":"SELECTION_ONLY_FOLD_LOCAL_OOS_RESEARCH","outer_geometry":[list(x) for x in _OUTER],"inner_expanding_geometry":[list(x) for x in _INNER],"signal":"exact frozen Turso market-row adjusted_close; binary64 return[t]=adjusted_close[t]/adjusted_close[t-1]-1; 474 tickers x 416 unique NYSE sessions; reject missing duplicate nonfinite zero previous or imputation","numeric_dependency":"CPython 3.14.4; NumPy 2.4.6 and GCC 15.2.0 pinned in external release closure although this pure implementation uses stdlib; IEEE754 binary64 little-endian evidence","materializer":"canonical target-major/source-major/lag-major f64-le replay evidence; exact materializer release and independent materializer evidence required externally","candidate_order":"outer_fold ASC,target_rank ASC,source_rank ASC excluding self,lag ASC 1..7","ols":"slope=(sum_xy-sum_x*sum_y/n)/(sum_x2-sum_x^2/n);intercept=mean_y-slope*mean_x","direction":"sign(prediction); prediction or actual zero uses training-majority; majority tie +1","baselines":"direction=training-majority rule evaluated on validation; return=training-mean evaluated on validation","pooling":"row pooled 52+52+45","skills":"direction=model_accuracy-baseline_accuracy;return=1-model_MSE/baseline_MSE;baseline_MSE_zero=>return_skill_zero","score":"(direction_skill+return_skill)/2","gates":"strict direction_skill>0 AND return_skill>0; any degenerate fit disqualifies","model_depth":"0..5 selected independent incoming source/lag edges per target/fold; no chain or layer semantics; no forced minimum; same source different lags allowed","ranking":"score DESC then candidate ordinal ASC","multiplicity":"NO_MULTIPLICITY_CONTROL_NO_FDR_CLAIM","outer_evaluation_dependency":"future separately approved single untouched outer evaluation; no retuning after inspection; excluded here","required_external_approval_envelope_identities":list(_REQUIRED_EXTERNAL_IDENTITIES),"downstream":"ZERO predictions recommendations orders ETF priors trading email validation promotion","terminal":"withhold all selected edges until exact 6277656-candidate global closure"})

class ContractError(ValueError):pass
@dataclass(frozen=True)
class SignalPanel: tickers:tuple[str,...];session_dates:tuple[str,...];rows:tuple[tuple[float,...],...];sha256:str
@dataclass(frozen=True)
class Lineage:
 dataset_version:str;snapshot_sha256:str;frozen_dataset_sha256:str;frozen_content_sha256:str;readback_sha256:str;calendar_sha256:str;signal_panel_sha256:str;preregistration_sha256:str;policy_sha256:str;selector_code_sha256:str;selector_release_sha256:str;dependency_closure_sha256:str;materializer_release_sha256:str;materializer_evidence_sha256:str;independent_review_event_sha256:str
 def fingerprint(self):return _sha(_cj(asdict(self)))
@dataclass(frozen=True)
class _Replay:
 inner_fold:int;train_indices:tuple[int,...];validation_indices:tuple[int,...];train_dates:tuple[str,...];validation_dates:tuple[str,...];train_x_hex:str;train_y_hex:str;validation_x_hex:str;actual_hex:str;prediction_hex:str;baseline_hex:str;sum_x:float;sum_y:float;sum_x2:float;sum_y2:float;sum_xy:float;intercept:float;slope:float;majority:int;model_correct:int;baseline_correct:int;model_sse:float;baseline_sse:float;degenerate:bool;chunk_sha256:str
@dataclass(frozen=True)
class Evidence:
 outer_fold:int;ordinal:int;source_rank:int;source:str;target_rank:int;target:str;lag:int;lineage:Lineage;lineage_fingerprint:str;panel_sha256:str;replay:tuple[_Replay,...];direction_accuracy:float;baseline_direction_accuracy:float;direction_skill:float;return_mse:float;baseline_return_mse:float;return_skill:float;score:float;qualified:bool;evidence_sha256:str
 def _payload(self):d=asdict(self);d.pop("evidence_sha256");return d
@dataclass(frozen=True)
class _Selected: outer_fold:int;target_rank:int;target:str;model_depth_rank:int;ordinal:int;evidence_sha256:str;panel_sha256:str;lineage_fingerprint:str
@dataclass(frozen=True)
class _Terminal: candidate_count:int;group_count:int;selection_count:int;stream_sha256:str;selection_manifest_sha256:str;panel_sha256:str;lineage_fingerprint:str;scientific_contract_sha256:str;terminal_sha256:str
@dataclass(frozen=True)
class CompleteRunResult: terminal:_Terminal;selections:tuple[_Selected,...]

def _f64(x):return b"".join(struct.pack("<d",float(v)) for v in x)
def _panel_raw(t,d,r):return b"V7PANEL\0"+struct.pack("<I",len(_cj(list(t))))+_cj(list(t))+struct.pack("<I",len(_cj(list(d))))+_cj(list(d))+b"".join(_f64(x) for x in r)
def build_signal_panel(tickers:tuple[str,...],session_dates:tuple[str,...],returns:Mapping[str,Sequence[float]])->SignalPanel:
 if len(tickers)!=474 or len(set(tickers))!=474 or tuple(sorted(tickers))!=tickers:raise ContractError("exact sorted 474 tickers required")
 if len(session_dates)!=416 or len(set(session_dates))!=416 or tuple(sorted(session_dates))!=session_dates:raise ContractError("exact 416 unique increasing dates required")
 try:p=tuple(date.fromisoformat(x) for x in session_dates)
 except ValueError as e:raise ContractError("invalid session date") from e
 if tuple(x.isoformat() for x in p)!=session_dates or set(returns)!=set(tickers):raise ContractError("calendar or ticker family mismatch")
 rows=[]
 for t in tickers:
  source_row=tuple(returns[t])
  if any(type(x)is bool for x in source_row):raise ContractError("panel row bool invalid")
  row=tuple(float(x) for x in source_row)
  if len(row)!=416 or any(not math.isfinite(x) or x<=-1 for x in row):raise ContractError("panel row invalid")
  rows.append(row)
 rows=tuple(rows);return SignalPanel(tickers,session_dates,rows,_sha(_panel_raw(tickers,session_dates,rows)))
def audit_signal_panel(panel:SignalPanel)->None:
 rebuilt=build_signal_panel(panel.tickers,panel.session_dates,MappingProxyType(dict(zip(panel.tickers,panel.rows))))
 if rebuilt!=panel:raise ContractError("panel identity mismatch")
def _ord(t,s,l):
 if type(t)is not int or type(s)is not int or type(l)is not int or not 0<=t<474 or not 0<=s<474 or t==s or not 1<=l<=7:raise ContractError("candidate coordinates invalid")
 return t*3311+(s if s<t else s-1)*7+l-1
def _fit(x,y):
 n=len(x);sx=math.fsum(x);sy=math.fsum(y);sx2=math.fsum(v*v for v in x);sy2=math.fsum(v*v for v in y);sxy=math.fsum(a*b for a,b in zip(x,y));vx=sx2-sx*sx/n;m=sy/n
 if vx<=0:return m,0.,sx,sy,sx2,sy2,sxy,True
 b=(sxy-sx*sy/n)/vx;return m-b*sx/n,b,sx,sy,sx2,sy2,sxy,False
def _dir(x,m):return 1 if x>0 else -1 if x<0 else m
def _lineage_ok(x,panel):
 d=asdict(x)
 if type(x.dataset_version)is not str or not x.dataset_version or any(len(v)!=64 or any(c not in "0123456789abcdef" for c in v) for k,v in d.items() if k!="dataset_version"):raise ContractError("lineage identity invalid")
 if x.signal_panel_sha256!=panel.sha256 or x.calendar_sha256!=_sha(_cj(list(panel.session_dates))):raise ContractError("lineage panel/calendar mismatch")
def evaluate_candidate(*,outer_fold:int,source_rank:int,source:str,target_rank:int,target:str,lag:int,panel:SignalPanel,lineage:Lineage)->Evidence:
 audit_signal_panel(panel);_lineage_ok(lineage,panel);o=next((x for x in _OUTER if x[0]==outer_fold),None)
 if o is None or panel.tickers[source_rank]!=source or panel.tickers[target_rank]!=target:raise ContractError("fold or ticker mapping invalid")
 ordinal=_ord(target_rank,source_rank,lag);ots,ote,ovs=o[1],o[2],o[5];sv=panel.rows[source_rank];tv=panel.rows[target_rank];replays=[];deg=False
 for g in _INNER:
  ats,ate=ots+g[1],ots+g[2];aps,ape=ots+g[3],ots+g[4];avs,ave=ots+g[5],ots+g[6]
  if not ats<=ate<aps<=ape<avs<=ave<=ote<ovs:raise ContractError("geometry violation")
  ti=tuple(range(ats+lag,ate+1));vi=tuple(range(avs,ave+1));x=tuple(sv[i-lag] for i in ti);y=tuple(tv[i] for i in ti);vx=tuple(sv[i-lag] for i in vi);a=tuple(tv[i] for i in vi)
  if len(x)<126 or any(not math.isfinite(z) for z in x+y+vx+a):raise ContractError("aligned data violation")
  intercept,slope,sx,sy,sx2,sy2,sxy,dg=_fit(x,y);deg|=dg;majority=1 if sum(z>0 for z in y)>=sum(z<0 for z in y) else -1;pred=tuple(intercept+slope*z for z in vx);base=(sy/len(y),)*len(a);mc=sum(_dir(q,majority)==_dir(z,majority) for q,z in zip(pred,a));bc=sum(majority==_dir(z,majority) for z in a);ms=math.fsum((z-q)**2 for z,q in zip(a,pred));bs=math.fsum((z-q)**2 for z,q in zip(a,base));parts=(g[0],ti,vi,tuple(panel.session_dates[i] for i in ti),tuple(panel.session_dates[i] for i in vi),_f64(x).hex(),_f64(y).hex(),_f64(vx).hex(),_f64(a).hex(),_f64(pred).hex(),_f64(base).hex(),sx,sy,sx2,sy2,sxy,intercept,slope,majority,mc,bc,ms,bs,dg);chunk=_sha(_cj(parts));replays.append(_Replay(*parts,chunk))
 n=sum(len(r.validation_indices) for r in replays);ma=sum(r.model_correct for r in replays)/n;ba=sum(r.baseline_correct for r in replays)/n;mm=math.fsum(r.model_sse for r in replays)/n;bm=math.fsum(r.baseline_sse for r in replays)/n;ds=ma-ba;rs=0. if bm<=0 else 1-mm/bm;q=not deg and ds>0 and rs>0
 empty=Evidence(outer_fold,ordinal,source_rank,source,target_rank,target,lag,lineage,lineage.fingerprint(),panel.sha256,tuple(replays),ma,ba,ds,mm,bm,rs,(ds+rs)/2,q,"");return replace(empty,evidence_sha256=_sha(_cj(empty._payload())))
def _decode(h,n):
 try:b=bytes.fromhex(h)
 except ValueError as e:raise ContractError("invalid f64 hex") from e
 if len(b)!=n*8:raise ContractError("f64 length mismatch")
 return tuple(x[0] for x in struct.iter_unpack("<d",b))
def _same(a,b):return struct.pack("<d",a)==struct.pack("<d",b)
def audit_evidence(e:Evidence,panel:SignalPanel)->None:
 audit_signal_panel(panel);_lineage_ok(e.lineage,panel)
 if e.evidence_sha256!=_sha(_cj(e._payload())) or e.lineage_fingerprint!=e.lineage.fingerprint() or e.panel_sha256!=panel.sha256 or e.ordinal!=_ord(e.target_rank,e.source_rank,e.lag) or panel.tickers[e.source_rank]!=e.source or panel.tickers[e.target_rank]!=e.target:raise ContractError("evidence identity mismatch")
 rebuilt=evaluate_candidate(outer_fold=e.outer_fold,source_rank=e.source_rank,source=e.source,target_rank=e.target_rank,target=e.target,lag=e.lag,panel=panel,lineage=e.lineage)
 if rebuilt!=e:raise ContractError("evidence replay mismatch")
 # Explicit byte checks make the panel binding auditable without trusting evaluator equality.
 sv,tv=panel.rows[e.source_rank],panel.rows[e.target_rank]
 for r in e.replay:
  if r.train_x_hex!=_f64(tuple(sv[i-e.lag] for i in r.train_indices)).hex() or r.train_y_hex!=_f64(tuple(tv[i] for i in r.train_indices)).hex() or r.validation_x_hex!=_f64(tuple(sv[i-e.lag] for i in r.validation_indices)).hex() or r.actual_hex!=_f64(tuple(tv[i] for i in r.validation_indices)).hex():raise ContractError("panel disconnect")
def select_complete_run(rows:Iterable[Evidence],panel:SignalPanel)->CompleteRunResult:
 audit_signal_panel(panel);f=1;o=0;count=groups=0;buf=[];held=[];stream=hashlib.sha256();lineage=None
 def emit_audited_group():
  # This closure is intentionally not a module-level callable.  Its only input
  # is the buffer populated below *after* audit_evidence bound every candidate
  # to the supplied panel and canonical stream position.
  if len(buf)!=_GROUP:raise ContractError("incomplete group")
  first=buf[0];target=first.target_rank;seen=bytearray(_GROUP)
  for candidate in buf:
   if (candidate.outer_fold,candidate.target_rank,candidate.lineage_fingerprint)!=(first.outer_fold,target,first.lineage_fingerprint):raise ContractError("group mixing")
   local=candidate.ordinal-target*_GROUP
   if not 0<=local<_GROUP or seen[local]:raise ContractError("duplicate/out-of-group")
   seen[local]=1
  if not all(seen):raise ContractError("missing group candidate")
  qualified=sorted((candidate for candidate in buf if candidate.qualified),key=lambda x:(-x.score,x.ordinal))[:5]
  return tuple(_Selected(candidate.outer_fold,candidate.target_rank,candidate.target,depth,candidate.ordinal,candidate.evidence_sha256,candidate.panel_sha256,candidate.lineage_fingerprint) for depth,candidate in enumerate(qualified,1))
 for e in rows:
  if (e.outer_fold,e.ordinal)!=(f,o):raise ContractError("noncanonical missing/duplicate stream")
  audit_evidence(e,panel);lineage=e.lineage_fingerprint if lineage is None else lineage
  if e.lineage_fingerprint!=lineage:raise ContractError("global lineage mixing")
  raw=_cj({**e._payload(),"evidence_sha256":e.evidence_sha256});stream.update(struct.pack("<I",len(raw)));stream.update(raw);buf.append(e);count+=1;o+=1
  if o%_GROUP==0:held.extend(emit_audited_group());buf=[];groups+=1
  if o==_PER_FOLD:f+=1;o=0
 if count!=_TOTAL or groups!=_GROUPS or f!=5 or o or buf:raise ContractError("incomplete global closure")
 if len(held)>_MAX:raise ContractError("depth cardinality violation")
 manifest=_cj([asdict(x) for x in held]);core={"candidate_count":count,"group_count":groups,"selection_count":len(held),"stream_sha256":stream.hexdigest(),"selection_manifest_sha256":_sha(manifest),"panel_sha256":panel.sha256,"lineage_fingerprint":lineage,"scientific_contract_sha256":_sha(SCIENTIFIC_CONTRACT_BYTES)};terminal=_Terminal(**core,terminal_sha256=_sha(_cj(core)));return CompleteRunResult(terminal,tuple(held))

def audit_complete_run_result(result:CompleteRunResult,rows:Iterable[Evidence],panel:SignalPanel)->None:
 """Recompute a terminal result from its complete source stream and compare it.

 Possessing a ``CompleteRunResult`` object is never sufficient evidence.  The
 caller must supply the immutable panel and the entire canonical Evidence
 stream so all candidates are replay-audited before any selection is accepted.
 """
 if type(result)is not CompleteRunResult or type(result.terminal)is not _Terminal or type(result.selections)is not tuple:raise ContractError("complete-run result type invalid")
 audit_signal_panel(panel);terminal=result.terminal
 core=asdict(terminal);claimed_terminal_sha=core.pop("terminal_sha256")
 if claimed_terminal_sha!=_sha(_cj(core)):raise ContractError("terminal digest mismatch")
 if terminal.panel_sha256!=panel.sha256 or terminal.scientific_contract_sha256!=_sha(SCIENTIFIC_CONTRACT_BYTES):raise ContractError("terminal panel/scientific contract mismatch")
 manifest=_cj([asdict(selection) for selection in result.selections])
 if terminal.selection_manifest_sha256!=_sha(manifest) or terminal.selection_count!=len(result.selections):raise ContractError("selection manifest mismatch")
 seen=set();depth_by_group={}
 for selection in result.selections:
  if type(selection)is not _Selected or selection.panel_sha256!=panel.sha256 or selection.lineage_fingerprint!=terminal.lineage_fingerprint:raise ContractError("selection identity mismatch")
  key=(selection.outer_fold,selection.target_rank);depth_by_group[key]=depth_by_group.get(key,0)+1
  if selection.model_depth_rank!=depth_by_group[key] or selection.model_depth_rank>5 or (selection.outer_fold,selection.ordinal) in seen:raise ContractError("selection depth/order/uniqueness mismatch")
  seen.add((selection.outer_fold,selection.ordinal))
 rebuilt=select_complete_run(rows,panel)
 if rebuilt!=result:raise ContractError("complete-run source replay mismatch")
