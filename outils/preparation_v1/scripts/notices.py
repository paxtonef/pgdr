#!/usr/bin/env python3
"""Validate a curated manual package and export explicit CPL mappings, without DB writes."""
import argparse, copy, hashlib, json, re, sys
from datetime import datetime, timezone
from pathlib import Path
import yaml
from pypdf import PdfReader
from PIL import Image

ENTRY_COLUMNS=('entry_id','manufacturer_designation','symbol_descriptor','colour','state','displayed_message','audible_signal','documented_meaning','documented_instruction','combined_with_entry_ids')
ASSET_COLUMNS=('image_file','image_sha256','pdf_page','page_reference')
# Optional per-entry linked_warnings (numbered manual warnings attached by printed cross-references).
# Exact key sets: an unknown key is rejected rather than silently dropped at export/import.
WARNING_COLUMNS=('number','text','printed_page','pdf_page','inline_pictograms')
PICTOGRAM_COLUMNS=('position','text_before','text_after','image_file','image_sha256','pdf_page','printed_page','identified_entry_ids','identification_basis')
# Optional per-entry provenance: pictograms printed inside documented_meaning, free-text notes,
# and field_sources {entry field: source passage} for fields documented outside the entry passage.
SOURCE_COLUMNS=('text','printed_page','pdf_page')
# Fields --export-cpl carries. Any other manifest field is listed in not_exported_fields, never silently dropped.
DOCUMENT_EXPORTED=('schema_version','document_id','title','edition','source_authority','source_locator','vehicle',
                   'applicability_period_start','applicability_period_end','applicability_period_note','manual_file','manual_sha256','review','entries')
ENTRY_EXPORTED=ENTRY_COLUMNS+ASSET_COLUMNS+('linked_warnings','inline_pictograms','notes','field_sources')

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

def check_image(root,name,sha):
    image=relative_file(root,name); check_hash(image,sha)
    with Image.open(image) as im:
        if im.format not in ('PNG','JPEG'): raise ValueError('PNG/JPEG required')
        im.verify()

def check_page(n,pages):
    if type(n) is not int or not 1<=n<=pages: raise ValueError('PDF page out of range')

def check_warnings(root,e,pages,seen):
    ws=e.get('linked_warnings',[])  # absent = no linked warning (schema v2 manifests without the field)
    if not isinstance(ws,list): raise ValueError('Invalid linked warnings')
    for w in ws:
        if not isinstance(w,dict) or set(w)!=set(WARNING_COLUMNS): raise ValueError('Invalid linked warning fields')
        for k in ('number','text','printed_page'): nonempty(w[k],k)
        check_page(w['pdf_page'],pages)
        check_pictograms(root,w['inline_pictograms'],w['text'],pages,seen)

def check_pictograms(root,ps,text,pages,seen):
    if not isinstance(ps,list): raise ValueError('Invalid inline pictograms')
    for p in ps:
        if not isinstance(p,dict) or set(p)!=set(PICTOGRAM_COLUMNS): raise ValueError('Invalid inline pictogram fields')
        for k in ('printed_page','identification_basis'): nonempty(p[k],k)
        for k in ('text_before','text_after'):
            if not isinstance(p[k],str): raise ValueError('Invalid pictogram context')
        # position = character offset in the anchoring text (warning text, or the entry's documented_meaning)
        pos=p['position']
        if type(pos) is not int or not 0<=pos<=len(text) or not text[:pos].endswith(p['text_before']) or not text[pos:].lstrip().startswith(p['text_after']): raise ValueError('Pictogram position does not match text')
        check_page(p['pdf_page'],pages); check_image(root,p['image_file'],p['image_sha256'])
        ids=p['identified_entry_ids']  # may be empty: pictogram not catalogued, explained by identification_basis
        if not isinstance(ids,list) or any(not isinstance(x,str) or x not in seen for x in ids) or len(set(ids))!=len(ids): raise ValueError('Invalid pictogram entry references')

def check_provenance(root,e,pages,seen):
    # Each field absent = empty (schema v2 manifests without it stay valid).
    check_pictograms(root,e.get('inline_pictograms',[]),e['documented_meaning'],pages,seen)
    notes=e.get('notes',[])
    if not isinstance(notes,list): raise ValueError('Invalid notes')
    for n in notes: nonempty(n,'note')
    fs=e.get('field_sources',{})
    if not isinstance(fs,dict): raise ValueError('Invalid field sources')
    for k,v in fs.items():
        if k not in ENTRY_COLUMNS or not isinstance(v,dict) or set(v)!=set(SOURCE_COLUMNS): raise ValueError('Invalid field source')
        for c in ('text','printed_page'): nonempty(v[c],c)
        check_page(v['pdf_page'],pages)

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
        check_page(e['pdf_page'],pages); check_image(root,e['image_file'],e['image_sha256'])
        ids=e['combined_with_entry_ids']
        if not isinstance(ids,list) or any(not isinstance(x,str) for x in ids) or len(set(ids))!=len(ids): raise ValueError('Invalid combined IDs')
    for e in entries:
        if any(x not in seen or x==e['entry_id'] for x in e['combined_with_entry_ids']): raise ValueError('Invalid combined reference')
        check_warnings(root,e,pages,seen); check_provenance(root,e,pages,seen)
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
            'entry_assets':[dict(entry_id=e['entry_id'],manual_order=i,**{k:e[k] for k in ASSET_COLUMNS}) for i,e in enumerate(d['entries'])],
            # Every linked warning of every entry, complete: exact text, pages and inline pictograms in manifest order.
            'entry_warnings':[dict(entry_id=e['entry_id'],warning_order=i,**{k:w[k] for k in WARNING_COLUMNS if k!='inline_pictograms'},
                                   inline_pictograms=[dict(pictogram_order=j,**{k:copy.deepcopy(p[k]) for k in PICTOGRAM_COLUMNS}) for j,p in enumerate(w['inline_pictograms'])])
                              for e in d['entries'] for i,w in enumerate(e.get('linked_warnings',[]))],
            'entry_inline_pictograms':[dict(entry_id=e['entry_id'],pictogram_order=j,**{k:copy.deepcopy(p[k]) for k in PICTOGRAM_COLUMNS})
                                       for e in d['entries'] for j,p in enumerate(e.get('inline_pictograms',[]))],
            'entry_notes':[dict(entry_id=e['entry_id'],note_order=i,note=n) for e in d['entries'] for i,n in enumerate(e.get('notes',[]))],
            'entry_field_sources':[dict(entry_id=e['entry_id'],field=k,**{c:v[c] for c in SOURCE_COLUMNS})
                                   for e in d['entries'] for k,v in sorted(e.get('field_sources',{}).items())],
            'not_exported_fields':not_exported(d)}

def not_exported(d):
    # Explicit report of manifest fields with no CPL destination yet (still covered by the review fingerprint).
    entries={}
    for e in d['entries']:
        for k in e:
            if k not in ENTRY_EXPORTED: entries[k]=entries.get(k,0)+1
    return {'document':sorted(k for k in d if k not in DOCUMENT_EXPORTED),'entries':{k:entries[k] for k in sorted(entries)}}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('manifest',type=Path); ap.add_argument('--select',nargs='+'); ap.add_argument('--fingerprint',action='store_true'); ap.add_argument('--export-cpl',action='store_true'); a=ap.parse_args()
    if a.fingerprint:
        print(content_fingerprint(read_structure(a.manifest))); return
    d=load_catalog(a.manifest)
    out=cpl_rows(d) if a.export_cpl else first_finding(d,a.select) if a.select else {'document_id':d['document_id'],'vehicle':d['vehicle'],'image_count':len(d['entries']),'status':'validated_local_package_NOT_loaded_in_CPL'}
    if a.export_cpl and (out['not_exported_fields']['document'] or out['not_exported_fields']['entries']):
        print('WARNING: manifest fields NOT exported to CPL: '+json.dumps(out['not_exported_fields'],ensure_ascii=False),file=sys.stderr)
    print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':
    try: main()
    except (ValueError,OSError,TypeError,KeyError,yaml.YAMLError): raise SystemExit('Manual rejected: invalid files, references, fields or review.')
