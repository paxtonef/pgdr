#!/usr/bin/env python3
"""Validate a curated manual package and export explicit CPL mappings, without DB writes."""
import argparse, hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path
import yaml
from pypdf import PdfReader
from PIL import Image

ENTRY_COLUMNS=('entry_id','manufacturer_designation','symbol_descriptor','colour','state','displayed_message','audible_signal','documented_meaning','documented_instruction','combined_with_entry_ids')
ASSET_COLUMNS=('image_file','image_sha256','pdf_page','page_reference')

def relative_file(root,name):
    if not isinstance(name,str) or not name or Path(name).is_absolute(): raise ValueError('Relative file path required')
    f=(root/name).resolve()
    if not f.is_relative_to(root.resolve()) or not f.is_file(): raise ValueError('Missing file or path outside package')
    return f

def nonempty(v,label):
    if not isinstance(v,str) or not v.strip(): raise ValueError(label+' required')

def content_fingerprint(d):
    # Bind review to EVERY manifest field except the review itself.
    payload={k:v for k,v in d.items() if k!='review'}
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def check_hash(file,expected):
    if not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected): raise ValueError('SHA256 required')
    if hashlib.sha256(file.read_bytes()).hexdigest()!=expected: raise ValueError('File fingerprint mismatch')

def read_structure(path):
    d=yaml.safe_load(path.read_text(encoding='utf-8')); root=path.parent
    if not isinstance(d,dict) or d.get('schema_version')!=2: raise ValueError('Schema version 2 required')
    for k in ('document_id','title','edition','source_locator'): nonempty(d.get(k),k)
    v=d.get('vehicle')
    if not isinstance(v,dict): raise ValueError('Vehicle required')
    for k in ('manufacturer','model','generation'): nonempty(v.get(k),k)
    if d.get('source_authority')!='manufacturer_official': raise ValueError('Manufacturer source required')
    for k in ('applicability_period_start','applicability_period_end','applicability_period_note'):
        if k not in d or (d[k] is not None and not isinstance(d[k],str)): raise ValueError('Explicit applicability fields required')
    manual=relative_file(root,d.get('manual_file')); check_hash(manual,d.get('manual_sha256'))
    pages=len(PdfReader(str(manual)).pages)
    entries=d.get('entries'); seen=set()
    if not isinstance(entries,list) or not entries: raise ValueError('No catalogue entries')
    for e in entries:
        if not isinstance(e,dict): raise ValueError('Entry object required')
        for k in ENTRY_COLUMNS+ASSET_COLUMNS:
            if k not in e: raise ValueError('Missing field: '+k)
        for k in ('entry_id','manufacturer_designation','page_reference','documented_meaning'): nonempty(e[k],k)
        if e['entry_id'] in seen: raise ValueError('Duplicate entry ID')
        seen.add(e['entry_id'])
        for k in ('symbol_descriptor','colour','displayed_message','audible_signal','documented_instruction'):
            if e[k] is not None and not isinstance(e[k],str): raise ValueError('Invalid optional text')
        if e['state'] not in (None,'fixed','flashing','unknown'): raise ValueError('Invalid documented state')
        if type(e['pdf_page']) is not int or not 1<=e['pdf_page']<=pages: raise ValueError('PDF page out of range')
        image=relative_file(root,e['image_file']); check_hash(image,e['image_sha256'])
        with Image.open(image) as im:
            if im.format not in ('PNG','JPEG'): raise ValueError('PNG/JPEG required')
            im.verify()
        ids=e['combined_with_entry_ids']
        if not isinstance(ids,list) or any(not isinstance(x,str) for x in ids) or len(set(ids))!=len(ids): raise ValueError('Invalid combined IDs')
    for e in entries:
        if any(x not in seen or x==e['entry_id'] for x in e['combined_with_entry_ids']): raise ValueError('Invalid combined reference')
    return d

def load_catalog(path):
    d=read_structure(path); r=d.get('review')
    if not isinstance(r,dict): raise ValueError('Named review required')
    for k in ('reviewer_id','reviewer_name'): nonempty(r.get(k),k)
    date=r.get('reviewed_at')
    if not isinstance(date,str): raise ValueError('Review date required')
    dt=datetime.fromisoformat(date.replace('Z','+00:00'))
    if dt.tzinfo is None or dt>datetime.now(timezone.utc): raise ValueError('Invalid review date')
    if r.get('status')!='approved' or r.get('content_sha256')!=content_fingerprint(d): raise ValueError('Review absent or obsolete')
    return d

def first_finding(catalog,selected):
    if not selected or len(selected)!=len(set(selected)): raise ValueError('Empty/duplicate selection')
    index={e['entry_id']:e for e in catalog['entries']}
    if any(x not in index for x in selected): raise ValueError('Selection outside catalogue')
    return [{'entry_id':x,'image_file':index[x]['image_file'],'designation':index[x]['manufacturer_designation'],
             'meaning':index[x]['documented_meaning'],'instruction':index[x]['documented_instruction'],
             'document_id':catalog['document_id'],'title':catalog['title'],'edition':catalog['edition'],
             'page_reference':index[x]['page_reference'],'pdf_page':index[x]['pdf_page']} for x in selected]

def colour_fallback(colour):
    if colour not in ('rouge','orange','jaune','vert','bleu','incertain'): raise ValueError('Unknown colour')
    cfg=yaml.safe_load((Path(__file__).resolve().parents[1]/'config/fallback_screens.en.yaml').read_text())
    key='red_or_uncertain' if colour in ('rouge','incertain') else 'other_colour'
    return dict(cfg['screens'][key],**cfg['shared'],human_verification_required=True,permission_to_drive=None)

def cpl_rows(d):
    doc={'manufacturer':d['vehicle']['manufacturer'],'document_id':d['document_id'],'document_title':d['title'],
         'edition':d['edition'],'source_authority':d['source_authority'],'source_locator':d['source_locator'],
         **{'applicability_'+k:v for k,v in d['vehicle'].items()},
         **{k:d[k] for k in ('applicability_period_start','applicability_period_end','applicability_period_note')}}
    return {'status':'validated_export_NOT_imported','document':doc,
            'entries':[{k:e[k] for k in ENTRY_COLUMNS} for e in d['entries']],
            'document_asset':{k:d[k] for k in ('manual_file','manual_sha256','review')},
            'entry_assets':[dict(entry_id=e['entry_id'],manual_order=i,**{k:e[k] for k in ASSET_COLUMNS}) for i,e in enumerate(d['entries'])]}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('manifest',type=Path); ap.add_argument('--select',nargs='+'); ap.add_argument('--fingerprint',action='store_true'); ap.add_argument('--export-cpl',action='store_true'); a=ap.parse_args()
    if a.fingerprint:
        print(content_fingerprint(read_structure(a.manifest))); return
    d=load_catalog(a.manifest)
    out=cpl_rows(d) if a.export_cpl else first_finding(d,a.select) if a.select else {'document_id':d['document_id'],'vehicle':d['vehicle'],'image_count':len(d['entries']),'status':'validated_local_package_NOT_loaded_in_CPL'}
    print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':
    try: main()
    except (ValueError,OSError,TypeError,KeyError,yaml.YAMLError): raise SystemExit('Manual rejected: invalid files, references, fields or review.')
