import sys, unittest, json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from trier_images import permutation, rank
from notices import first_finding, colour_fallback
class Contracts(unittest.TestCase):
    def test_complete_permutation(self):
        self.assertEqual(permutation('{"ordered_entry_ids":["b","a"]}',['a','b']),['b','a'])
    def test_no_filter_duplicates_foreign_or_assertion(self):
        for obj in ({'ordered_entry_ids':['a']},{'ordered_entry_ids':['a','a']},{'ordered_entry_ids':['a','c']},{'ordered_entry_ids':['a','b'],'colour':'red'}):
            with self.subTest(obj=obj), self.assertRaises(ValueError): permutation(json.dumps(obj),['a','b'])
    def test_unavailable_keeps_entire_catalogue(self):
        d={'entries':[{'entry_id':'a'},{'entry_id':'b'}]}
        self.assertEqual(rank(d,Path('.'),Path('missing'),{'enabled':False},None)['ordered_entry_ids'],['a','b'])
    def test_missing_consent_prevents_send(self):
        with self.assertRaises(ValueError): rank({'entries':[]},Path('.'),Path('missing'),{'enabled':True,'recipient_name':'X'},None)
    def test_red_and_uncertain_stop(self):
        for c in ('rouge','incertain'):
            r=colour_fallback(c); self.assertIn('Stop',r['heading']); self.assertIsNone(r['permission_to_drive']); self.assertTrue(r['human_verification_required'])
    def test_other_colours_do_not_authorize(self):
        for c in ('orange','jaune','vert','bleu'): self.assertIsNone(colour_fallback(c)['permission_to_drive'])
    def test_multi_selection_exact_text_and_page(self):
        entries=[{'entry_id':x,'manufacturer_designation':x,'image_file':'image.png','documented_meaning':'Texte exact « A »','documented_instruction':'Consigne exacte.','page_reference':'12','pdf_page':14} for x in ('a','b')]
        d={'document_id':'D','title':'Notice','edition':'E','entries':entries}
        r=first_finding(d,['b','a']); self.assertEqual([x['entry_id'] for x in r],['b','a']); self.assertEqual(r[0]['meaning'],entries[0]['documented_meaning']); self.assertEqual(r[0]['pdf_page'],14)
        with self.assertRaises(ValueError): first_finding(d,['c'])
        with self.assertRaises(ValueError): first_finding(d,['a','a'])
if __name__=='__main__': unittest.main()
