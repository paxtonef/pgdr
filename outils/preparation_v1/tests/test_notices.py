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
