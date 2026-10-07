import copy, hashlib, json, sys, tempfile, unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import yaml
from PIL import Image
from pypdf import PdfWriter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from notices import load_catalog, content_fingerprint, cpl_rows, colour_fallback
from trier_images import permutation, rank

class NoticeValidation(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.path=self.root/'manifest.yaml'
        pdf=PdfWriter(); pdf.add_blank_page(width=100,height=100); pdf.write(str(self.root/'manual.pdf'))
        Image.new('RGB',(8,8),'red').save(self.root/'image.png')
        def sha(name): return hashlib.sha256((self.root/name).read_bytes()).hexdigest()
        self.d={'schema_version':2,'document_id':'TEST-NOT-MANUFACTURER','title':'Synthetic test','edition':'E','source_authority':'manufacturer_official','source_locator':'synthetic fixture only','vehicle':{'manufacturer':'TEST','model':'M','generation':'G'},'applicability_period_start':None,'applicability_period_end':None,'applicability_period_note':None,'manual_file':'manual.pdf','manual_sha256':sha('manual.pdf'),'entries':[{'entry_id':str(i),'manufacturer_designation':'Example','symbol_descriptor':None,'colour':'red','state':'fixed','displayed_message':None,'audible_signal':None,'documented_meaning':'Exact text','documented_instruction':None,'combined_with_entry_ids':[],'image_file':'image.png','image_sha256':sha('image.png'),'pdf_page':1,'page_reference':'A-1'} for i in range(2)]}
        self.approve()
    def approve(self):
        self.d['review']={'status':'approved','reviewer_id':'test-user','reviewer_name':'Synthetic reviewer','reviewed_at':datetime.now(timezone.utc).isoformat(),'content_sha256':content_fingerprint(self.d)}
    def save(self): self.path.write_text(yaml.safe_dump(self.d),encoding='utf-8')
    def valid(self): self.save(); return load_catalog(self.path)
    def rejected(self,approve=False):
        if approve:self.approve()
        self.save()
        with self.assertRaises((ValueError,OSError)):load_catalog(self.path)
    def test_complete_package_and_existing_fields_exported(self):
        rows=cpl_rows(self.valid()); e=rows['entries'][0]
        self.assertEqual(e['colour'],'red'); self.assertEqual(e['state'],'fixed'); self.assertIsNone(e['documented_instruction']); self.assertEqual(rows['entry_assets'][1]['manual_order'],1)
    def test_missing_image(self): self.d['entries'][0]['image_file']='missing.png'; self.rejected(True)
    def test_missing_manual(self): self.d['manual_file']='missing.pdf'; self.rejected(True)
    def test_outside_path(self): self.d['entries'][0]['image_file']='../outside.png'; self.rejected(True)
    def test_absolute_path(self): self.d['manual_file']=str(self.root/'manual.pdf'); self.rejected(True)
    def test_symlink_escape(self):
        with tempfile.TemporaryDirectory() as outside:
            f=Path(outside)/'x.png'; f.write_bytes((self.root/'image.png').read_bytes()); (self.root/'link.png').symlink_to(f)
            self.d['entries'][0]['image_file']='link.png'; self.rejected(True)
    def test_manual_hash(self): self.d['manual_sha256']='0'*64; self.rejected(True)
    def test_image_hash(self): self.d['entries'][0]['image_sha256']='0'*64; self.rejected(True)
    def test_corrupt_image_with_matching_hash(self):
        (self.root/'image.png').write_bytes(b'not an image'); self.d['entries'][0]['image_sha256']=hashlib.sha256(b'not an image').hexdigest()
        self.approve(); self.save()
        with self.assertRaises(OSError):load_catalog(self.path)
    def test_duplicate_ids(self): self.d['entries'][1]['entry_id']='0'; self.rejected(True)
    def test_missing_page_reference(self): self.d['entries'][0]['page_reference']=''; self.rejected(True)
    def test_page_out_of_range(self): self.d['entries'][0]['pdf_page']=2; self.rejected(True)
    def test_boolean_page(self): self.d['entries'][0]['pdf_page']=True; self.rejected(True)
    def test_missing_colour_field(self): del self.d['entries'][0]['colour']; self.rejected(True)
    def test_invalid_state(self): self.d['entries'][0]['state']='probably flashing'; self.rejected(True)
    def test_combined_reference_missing(self): self.d['entries'][0]['combined_with_entry_ids']=['other']; self.rejected(True)
    def test_combined_reference_self(self): self.d['entries'][0]['combined_with_entry_ids']=['0']; self.rejected(True)
    def test_combined_reference_valid(self): self.d['entries'][0]['combined_with_entry_ids']=['1']; self.approve(); self.assertEqual(self.valid()['entries'][0]['combined_with_entry_ids'],['1'])
    def test_review_name_missing(self): self.d['review']['reviewer_name']=''; self.rejected()
    def test_review_identity_missing(self): self.d['review']['reviewer_id']=''; self.rejected()
    def test_review_date_no_timezone(self): self.d['review']['reviewed_at']='2026-01-01'; self.rejected()
    def test_review_future(self): self.d['review']['reviewed_at']='2999-01-01T00:00:00Z'; self.rejected()
    def test_review_pending(self): self.d['review']['status']='pending'; self.rejected()
    def test_review_obsolete_after_text_change(self): self.d['entries'][0]['documented_meaning']='Changed'; self.rejected()
    def test_review_obsolete_after_vehicle_change(self): self.d['vehicle']['generation']='G2'; self.rejected()
    def test_review_obsolete_after_reorder(self): self.d['entries'].reverse(); self.rejected()
    def test_null_colour_preserved(self): self.d['entries'][0]['colour']=None; self.approve(); self.assertIsNone(self.valid()['entries'][0]['colour'])

class LinkedWarnings(NoticeValidation):
    # Synthetic notice only: invented warnings and pictograms, no manufacturer content.
    STOP='If the test symbol lights up while moving, stop the vehicle immediately and call a test workshop.'
    def setUp(self):
        super().setUp()
        Image.new('RGB',(4,4),'black').save(self.root/'picto.png')
        self.picto_sha=hashlib.sha256((self.root/'picto.png').read_bytes()).hexdigest()
        self.d['entries'][0]['linked_warnings']=[
            {'number':'1)','text':self.STOP,'printed_page':'A-1','pdf_page':1,'inline_pictograms':[
                self.picto(self.STOP,12,['0']),self.picto(self.STOP,len(self.STOP),[],'Not catalogued: shape absent from synthetic catalogue.')]},
            {'number':'2)','text':'A second synthetic warning for the same entry.','printed_page':'A-2','pdf_page':1,'inline_pictograms':[]}]
        self.d['entries'][1]['linked_warnings']=[]
        self.approve()
    def picto(self,text,pos,ids,basis='Same synthetic drawing as entry 0.'):
        return {'position':pos,'text_before':text[:pos][-8:],'text_after':text[pos:].lstrip()[:8],'image_file':'picto.png','image_sha256':self.picto_sha,'pdf_page':1,'printed_page':'A-1','identified_entry_ids':ids,'identification_basis':basis}
    def exported(self): return cpl_rows(self.valid())['entry_warnings']
    def test_stop_instruction_exported_identically_with_pages_and_pictograms(self):
        w=self.exported()[0]; src=self.d['entries'][0]['linked_warnings'][0]
        self.assertEqual((w['entry_id'],w['warning_order']),('0',0)); self.assertEqual(w['text'],self.STOP); self.assertIn('stop the vehicle immediately',w['text'])
        self.assertEqual({k:w[k] for k in ('number','printed_page','pdf_page')},{'number':'1)','printed_page':'A-1','pdf_page':1})
        self.assertEqual([{k:v for k,v in p.items() if k!='pictogram_order'} for p in w['inline_pictograms']],src['inline_pictograms'])
        self.assertEqual([p['pictogram_order'] for p in w['inline_pictograms']],[0,1])
    def test_several_warnings_for_one_entry(self):
        out=self.exported(); self.assertEqual([(w['entry_id'],w['warning_order'],w['number']) for w in out],[('0',0,'1)'),('0',1,'2)')])
        self.assertEqual(out[1]['inline_pictograms'],[])
    def test_entry_without_warning(self):
        self.assertNotIn('1',[w['entry_id'] for w in self.exported()])
        del self.d['entries'][1]['linked_warnings']; self.approve(); self.assertNotIn('1',[w['entry_id'] for w in self.exported()])
    def test_manifest_without_any_warning_field_still_valid(self):
        for e in self.d['entries']: e.pop('linked_warnings')
        self.approve(); self.assertEqual(self.exported(),[])
    def test_obsolete_after_warning_text_change(self): self.d['entries'][0]['linked_warnings'][0]['text']=self.STOP.replace('immediately','soon'); self.rejected()
    def test_obsolete_after_warning_printed_page_change(self): self.d['entries'][0]['linked_warnings'][0]['printed_page']='A-9'; self.rejected()
    def test_obsolete_after_warning_pdf_page_change(self):
        pdf=PdfWriter(); pdf.add_blank_page(width=100,height=100); pdf.add_blank_page(width=100,height=100); pdf.write(str(self.root/'manual.pdf'))
        self.d['manual_sha256']=hashlib.sha256((self.root/'manual.pdf').read_bytes()).hexdigest(); self.approve(); self.valid()
        self.d['entries'][0]['linked_warnings'][0]['pdf_page']=2; self.rejected()
    def test_obsolete_after_pictogram_reference_change(self): self.d['entries'][0]['linked_warnings'][0]['inline_pictograms'][1]['identified_entry_ids']=['1']; self.rejected()
    def test_obsolete_after_pictogram_basis_change(self): self.d['entries'][0]['linked_warnings'][0]['inline_pictograms'][0]['identification_basis']='Changed'; self.rejected()
    def test_obsolete_after_pictogram_removed(self): self.d['entries'][0]['linked_warnings'][0]['inline_pictograms'].pop(); self.rejected()
    def test_obsolete_after_pictogram_image_change(self):
        Image.new('RGB',(4,4),'white').save(self.root/'picto2.png')
        p=self.d['entries'][0]['linked_warnings'][0]['inline_pictograms'][0]; p['image_file']='picto2.png'; p['image_sha256']=hashlib.sha256((self.root/'picto2.png').read_bytes()).hexdigest(); self.rejected()
    def test_obsolete_after_warning_removed(self): self.d['entries'][0]['linked_warnings'].pop(0); self.rejected()
    def test_obsolete_after_warning_field_removed(self): del self.d['entries'][0]['linked_warnings']; self.rejected()
    def test_pictogram_hash_mismatch(self): self.d['entries'][0]['linked_warnings'][0]['inline_pictograms'][0]['image_sha256']='0'*64; self.rejected(True)
    def test_pictogram_position_mismatch(self): self.d['entries'][0]['linked_warnings'][0]['inline_pictograms'][0]['position']=3; self.rejected(True)
    def test_pictogram_unknown_entry(self): self.d['entries'][0]['linked_warnings'][0]['inline_pictograms'][0]['identified_entry_ids']=['other']; self.rejected(True)
    def test_warning_unknown_field_rejected_not_dropped(self): self.d['entries'][0]['linked_warnings'][0]['extra']='x'; self.rejected(True)
    def test_warning_missing_page(self): del self.d['entries'][0]['linked_warnings'][0]['pdf_page']; self.rejected(True)
    def test_warning_page_out_of_range(self): self.d['entries'][0]['linked_warnings'][0]['pdf_page']=2; self.rejected(True)
    def test_warning_empty_text(self): self.d['entries'][0]['linked_warnings'][0]['text']=''; self.rejected(True)

class SortContract(unittest.TestCase):
    def test_single_json_fence(self): self.assertEqual(permutation('```json\n{"ordered_entry_ids":["b","a"]}\n```',['a','b']),['b','a'])
    def test_comment_outside_fence_rejected(self):
        with self.assertRaises(ValueError):permutation('Here it is:\n```json\n{"ordered_entry_ids":[]}\n```',[])
    def test_two_fences_rejected(self):
        with self.assertRaises(ValueError):permutation('```json\n{"ordered_entry_ids":[]}\n```\n```json\n{}\n```',[])
    def test_duplicate_json_key_rejected(self):
        with self.assertRaises(ValueError):permutation('{"ordered_entry_ids":[],"ordered_entry_ids":[]}',[])
    def test_unconfigured_limit_falls_back_before_network(self):
        cfg={'enabled':True,'recipient_name':'LOCAL','endpoint':'http://localhost:1234/v1/chat/completions','model_id':'test'}
        with patch('urllib.request.build_opener') as network:
            r=rank({'entries':[{'entry_id':'a'}]},Path('.'),Path('no-photo'),cfg,'LOCAL')
            self.assertEqual(r['mode'],'manual_order'); network.assert_not_called()
    def test_seventy_images_bounded_and_complete(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); Image.new('RGB',(8,8)).save(root/'image.png')
            entries=[{'entry_id':str(i),'image_file':'image.png'} for i in range(70)]
            cfg={'enabled':True,'recipient_name':'LOCAL','endpoint':'http://localhost:1234/v1/chat/completions','model_id':'test','max_images_per_request':5,'max_request_bytes':100000,'max_batches':20}
            requests=[]
            class Response:
                def __init__(self,raw):self.raw=raw
                def __enter__(self):return self
                def __exit__(self,*a):pass
                def read(self,n):return self.raw
            class Client:
                def open(self,req,timeout):
                    b=json.loads(req.data); content=b['messages'][1]['content']; requests.append(content)
                    ids=[x['text'][9:] for x in content if x['type']=='text' and x['text'].startswith('Image ID ')]
                    text='```json\n'+json.dumps({'ordered_entry_ids':list(reversed(ids))})+'\n```'
                    return Response(json.dumps({'choices':[{'message':{'content':text}}]}).encode())
            with patch('urllib.request.build_opener',return_value=Client()):
                out=rank({'entries':entries},root,root/'image.png',cfg,'LOCAL')
            self.assertEqual(len(requests),18)
            self.assertTrue(all(sum(x['type']=='image_url' for x in c)<=5 for c in requests))
            self.assertEqual(set(out['ordered_entry_ids']),{str(i) for i in range(70)})
            self.assertEqual(len(out['ordered_entry_ids']),70); self.assertFalse(out['global_similarity_rank'])

class ScreenCopy(unittest.TestCase):
    def test_exact_note_red_screen(self):
        r=colour_fallback('rouge'); self.assertEqual(r['paragraphs'][-1],'Have the situation checked by a person before resuming your journey.'); self.assertFalse(r['show_status_indicator']); self.assertFalse(r['handoff_implied'])
    def test_exact_note_other_screen(self):
        r=colour_fallback('vert'); self.assertEqual(r['heading'],'Warning light unresolved — human verification required'); self.assertEqual(r['paragraphs'][-1],'This result does not authorise you to continue driving. Have the situation checked by a person before deciding whether to continue.')

class EntryProvenance(unittest.TestCase):
    # Synthetic notice only: entry-level pictograms, notes and field sources.
    MEANING='The test symbol means a synthetic fault.'
    def setUp(self):
        self.base=NoticeValidation('test_complete_package_and_existing_fields_exported'); self.base.setUp(); self.addCleanup(self.base.doCleanups)
        b=self.base; Image.new('RGB',(4,4),'black').save(b.root/'picto.png')
        self.sha=hashlib.sha256((b.root/'picto.png').read_bytes()).hexdigest()
        e=b.d['entries'][0]; e['documented_meaning']=self.MEANING
        e['inline_pictograms']=[{'position':15,'text_before':'test symbol','text_after':'means a','image_file':'picto.png','image_sha256':self.sha,'pdf_page':1,'printed_page':'A-1','identified_entry_ids':['1'],'identification_basis':'Same synthetic drawing as entry 1.'}]
        e['notes']=['First synthetic note.','Second synthetic note.']
        e['field_sources']={'audible_signal':{'text':'A synthetic chime sounds.','printed_page':'A-1','pdf_page':1}}
        e['where_provided']=False; b.d['coverage']={'entries':2}
        b.approve()
    def rows(self): return cpl_rows(self.base.valid())
    def mutate_rejected(self,f): f(self.base.d['entries'][0]); self.base.rejected()
    def test_pictograms_exported_faithfully(self):
        out=self.rows()['entry_inline_pictograms']; src=self.base.d['entries'][0]['inline_pictograms']
        self.assertEqual([(o['entry_id'],o['pictogram_order']) for o in out],[('0',0)])
        self.assertEqual([{k:v for k,v in o.items() if k not in ('entry_id','pictogram_order')} for o in out],src)
    def test_notes_exported_in_order(self):
        self.assertEqual(self.rows()['entry_notes'],[{'entry_id':'0','note_order':0,'note':'First synthetic note.'},{'entry_id':'0','note_order':1,'note':'Second synthetic note.'}])
    def test_field_sources_exported(self):
        self.assertEqual(self.rows()['entry_field_sources'],[{'entry_id':'0','field':'audible_signal','text':'A synthetic chime sounds.','printed_page':'A-1','pdf_page':1}])
    def test_unsupported_fields_reported_not_silently_dropped(self):
        self.assertEqual(self.rows()['not_exported_fields'],{'document':['coverage'],'entries':{'where_provided':1}})
    def test_entry_without_provenance(self):
        r=self.rows(); self.assertNotIn('1',[x['entry_id'] for k in ('entry_inline_pictograms','entry_notes','entry_field_sources') for x in r[k]])
    def test_obsolete_after_pictogram_position_change(self):
        def f(e): p=e['inline_pictograms'][0]; p.update(position=8,text_before='The test',text_after='symbol')
        self.mutate_rejected(f)
    def test_obsolete_after_pictogram_reference_change(self): self.mutate_rejected(lambda e:e['inline_pictograms'][0].update(identified_entry_ids=[]))
    def test_obsolete_after_pictogram_image_change(self):
        Image.new('RGB',(4,4),'white').save(self.base.root/'picto2.png'); sha=hashlib.sha256((self.base.root/'picto2.png').read_bytes()).hexdigest()
        self.mutate_rejected(lambda e:e['inline_pictograms'][0].update(image_file='picto2.png',image_sha256=sha))
    def test_obsolete_after_pictogram_removed(self): self.mutate_rejected(lambda e:e['inline_pictograms'].pop())
    def test_obsolete_after_note_change(self): self.mutate_rejected(lambda e:e['notes'].__setitem__(0,'Changed note.'))
    def test_obsolete_after_note_removed(self): self.mutate_rejected(lambda e:e['notes'].pop())
    def test_obsolete_after_notes_field_removed(self): self.mutate_rejected(lambda e:e.pop('notes'))
    def test_obsolete_after_source_text_change(self): self.mutate_rejected(lambda e:e['field_sources']['audible_signal'].update(text='Changed.'))
    def test_obsolete_after_source_page_change(self): self.mutate_rejected(lambda e:e['field_sources']['audible_signal'].update(printed_page='A-9'))
    def test_obsolete_after_source_removed(self): self.mutate_rejected(lambda e:e['field_sources'].pop('audible_signal'))
    def test_obsolete_after_unsupported_field_change(self): self.mutate_rejected(lambda e:e.update(where_provided=True))
    def test_pictogram_position_mismatch(self): self.base.d['entries'][0]['inline_pictograms'][0]['position']=3; self.base.rejected(True)
    def test_pictogram_hash_mismatch(self): self.base.d['entries'][0]['inline_pictograms'][0]['image_sha256']='0'*64; self.base.rejected(True)
    def test_empty_note_rejected(self): self.base.d['entries'][0]['notes']=['']; self.base.rejected(True)
    def test_source_for_unknown_field_rejected(self): self.base.d['entries'][0]['field_sources']={'not_a_field':{'text':'x','printed_page':'1','pdf_page':1}}; self.base.rejected(True)
    def test_source_page_out_of_range(self): self.base.d['entries'][0]['field_sources']['audible_signal']['pdf_page']=2; self.base.rejected(True)
