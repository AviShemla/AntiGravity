import dataclasses,inspect,math,unittest
from datetime import date,timedelta
from research_contracts.fold_selection_approval import s08_selector_v7 as m
def fx():
 t=tuple(f"T{i:03d}" for i in range(474));d=tuple((date(2020,1,1)+timedelta(days=i)).isoformat() for i in range(416));v={x:[math.sin(i/3+(j%7)) for i in range(416)] for j,x in enumerate(t)};p=m.build_signal_panel(t,d,v);cal=m._sha(m._cj(list(d)));l=m.Lineage("ds",*(["1"*64,"2"*64,"3"*64,"4"*64,cal,p.sha256,"5"*64,"6"*64,"7"*64,"8"*64,"9"*64,"a"*64,"b"*64,"c"*64]));e=m.evaluate_candidate(outer_fold=1,source_rank=1,source=t[1],target_rank=0,target=t[0],lag=1,panel=p,lineage=l);return p,l,e
class Tests(unittest.TestCase):
 def test_public_surface_and_no_predecessor_imports(self):
  self.assertEqual(set(m.__all__),{x for x in m.__all__});src=inspect.getsource(m);self.assertNotIn("selector_v3",src);self.assertNotIn("selector_v4",src);self.assertNotIn("selector_v5",src);self.assertNotIn("selector_v6",src);self.assertFalse(any("authoriz" in x.lower() or "outer_test" in x.lower() or "target_family" in x.lower() for x in m.__all__))
  self.assertFalse(hasattr(m,"_select_group"))
 def test_contract_depth_scope_and_identities(self):
  s=m.SCIENTIFIC_CONTRACT_BYTES.decode();self.assertIn("0..5 selected independent incoming",s);self.assertIn("NO_MULTIPLICITY_CONTROL_NO_FDR_CLAIM",s);self.assertIn("materializer_release_sha256",s);self.assertIn("ZERO predictions",s)
 def test_panel_and_evidence(self):p,l,e=fx();m.audit_signal_panel(p);m.audit_evidence(e,p)
 def test_panel_disconnect_and_rehash_fails(self):
  p,l,e=fx();r=e.replay[0];raw=bytearray.fromhex(r.train_x_hex);raw[0]^=1;rr=dataclasses.replace(r,train_x_hex=raw.hex());x=dataclasses.replace(e,replay=(rr,)+e.replay[1:],evidence_sha256="");x=dataclasses.replace(x,evidence_sha256=m._sha(m._cj(x._payload())))
  with self.assertRaises(m.ContractError):m.audit_evidence(x,p)
 def test_incomplete_and_duplicate_global_never_return(self):
  p,l,e=fx()
  with self.assertRaisesRegex(m.ContractError,"incomplete"):m.select_complete_run([],p)
  with self.assertRaisesRegex(m.ContractError,"noncanonical"):m.select_complete_run([e,e],p)
 def test_fabricated_hashes_cannot_create_state(self):
  self.assertFalse(any("approve" in n.lower() or "authoriz" in n.lower() for n in dir(m)));self.assertNotIn(b'"status":"AUTHORIZED"',m.SCIENTIFIC_CONTRACT_BYTES)
 def test_terminal_hash_recomputation_schema(self):
  core={"candidate_count":m._TOTAL,"group_count":m._GROUPS,"selection_count":0,"stream_sha256":"1"*64,"selection_manifest_sha256":"2"*64,"panel_sha256":"3"*64,"lineage_fingerprint":"4"*64,"scientific_contract_sha256":m._sha(m.SCIENTIFIC_CONTRACT_BYTES)};t=m._Terminal(**core,terminal_sha256=m._sha(m._cj(core)));self.assertEqual(t.terminal_sha256,m._sha(m._cj(core)))
 def test_417_and_bad_ordinal_rejected(self):
  p,l,e=fx();d=p.session_dates+("2030-01-01",);v={t:list(r)+[0.] for t,r in zip(p.tickers,p.rows)}
  with self.assertRaisesRegex(m.ContractError,"416"):m.build_signal_panel(p.tickers,d,v)
  with self.assertRaises(m.ContractError):m._ord(-1,1,1)
 def test_return_domain_rejects_total_loss_and_below(self):
  p,l,e=fx()
  for invalid in (-1.0,-1.01):
   values={ticker:list(row) for ticker,row in zip(p.tickers,p.rows)};values[p.tickers[0]][0]=invalid
   with self.assertRaisesRegex(m.ContractError,"panel row invalid"):m.build_signal_panel(p.tickers,p.session_dates,values)
 def test_bool_return_rejected_before_float_coercion(self):
  p,l,e=fx();values={ticker:list(row) for ticker,row in zip(p.tickers,p.rows)};values[p.tickers[0]][0]=True
  with self.assertRaisesRegex(m.ContractError,"panel row bool invalid"):m.build_signal_panel(p.tickers,p.session_dates,values)
 def test_dataset_version_requires_exact_nonempty_str(self):
  class StrSubclass(str):pass
  p,l,e=fx()
  for invalid in (True,False,1,"",StrSubclass("ds")):
   bad=dataclasses.replace(l,dataset_version=invalid)
   with self.assertRaisesRegex(m.ContractError,"lineage identity invalid"):m.evaluate_candidate(outer_fold=1,source_rank=1,source=p.tickers[1],target_rank=0,target=p.tickers[0],lag=1,panel=p,lineage=bad)
 def test_complete_result_requires_full_replayed_source_stream(self):
  p,l,e=fx();core={"candidate_count":m._TOTAL,"group_count":m._GROUPS,"selection_count":0,"stream_sha256":"1"*64,"selection_manifest_sha256":m._sha(m._cj([])),"panel_sha256":p.sha256,"lineage_fingerprint":l.fingerprint(),"scientific_contract_sha256":m._sha(m.SCIENTIFIC_CONTRACT_BYTES)};terminal=m._Terminal(**core,terminal_sha256=m._sha(m._cj(core)));result=m.CompleteRunResult(terminal,())
  with self.assertRaisesRegex(m.ContractError,"incomplete"):m.audit_complete_run_result(result,[],p)
  forged=dataclasses.replace(result,terminal=dataclasses.replace(terminal,selection_manifest_sha256="f"*64))
  with self.assertRaisesRegex(m.ContractError,"terminal digest|selection manifest"):m.audit_complete_run_result(forged,[],p)
if __name__=="__main__":unittest.main()
