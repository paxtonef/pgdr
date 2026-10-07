#!/usr/bin/env python3
"""Optional ordering only. Output is always the entire catalogue. No diagnosis."""
import argparse, base64, json, os, re, urllib.request
from pathlib import Path
from urllib.parse import urlsplit
import yaml
from notices import load_catalog, relative_file

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args): return None

def permutation(content,ids):
    if not isinstance(content,str): raise ValueError('Text response required')
    content=content.strip()
    if content.startswith('```'):
        match=re.fullmatch(r'```(?:json)?\s*\n(.*?)\n```',content,re.DOTALL|re.IGNORECASE)
        if not match: raise ValueError('Single JSON block required')
        content=match.group(1)
    def unique_keys(pairs):
        result={}
        for k,v in pairs:
            if k in result: raise ValueError('Duplicate JSON key')
            result[k]=v
        return result
    obj=json.loads(content,object_pairs_hook=unique_keys)
    if not isinstance(obj,dict) or set(obj)!={'ordered_entry_ids'}: raise ValueError('Réponse non limitée au tri')
    order=obj['ordered_entry_ids']
    if not isinstance(order,list) or any(not isinstance(x,str) for x in order): raise ValueError('Ordre invalide')
    if len(order)!=len(ids) or len(set(order))!=len(order) or set(order)!=set(ids): raise ValueError('Catalogue incomplet ou modifié')
    return order

def image_data(file):
    raw=file.read_bytes()
    if len(raw)>15*1024*1024: raise ValueError('Image trop volumineuse')
    if raw.startswith(b'\x89PNG\r\n\x1a\n'): mime='image/png'
    elif raw.startswith(b'\xff\xd8\xff'): mime='image/jpeg'
    else: raise ValueError('PNG/JPEG requis')
    return 'data:'+mime+';base64,'+base64.b64encode(raw).decode('ascii')

def rank(catalog,root,photo,config,consent):
    ids=[e['entry_id'] for e in catalog['entries']]
    fallback={'ordered_entry_ids':ids,'mode':'manual_order','all_images_available':True}
    if not config.get('enabled'): return fallback
    # Consent must be supplied BEFORE any bytes are sent. Never silently bypass it.
    if consent!=config.get('recipient_name') or not consent: raise ValueError('Consentement nommant le destinataire requis')
    try:
        endpoint=config['endpoint']; host=urlsplit(endpoint)
        if host.username or host.password: raise ValueError('Identifiants dans URL refusés')
        local=host.hostname in ('127.0.0.1','localhost','::1')
        if not local and host.scheme!='https': raise ValueError('HTTPS requis')
        model=config.get('model_id')
        if not isinstance(model,str) or not model.strip(): return fallback
        limit=config.get('max_images_per_request')
        byte_limit=config.get('max_request_bytes')
        max_batches=config.get('max_batches')
        if any(type(x) is not int or x<1 for x in (limit,byte_limit,max_batches)) or limit<2: return fallback
        size=limit-1  # one photo plus at most limit-1 catalogue images
        groups=[catalog['entries'][i:i+size] for i in range(0,len(ids),size)]
        if len(groups)>max_batches: return fallback
        photo_data=image_data(photo)
        headers={'Content-Type':'application/json'}
        env=config.get('api_key_env'); key=os.environ.get(env,'') if env else ''
        if not local and not key: return fallback
        if key: headers['Authorization']='Bearer '+key
        if not local and not config.get('routing_verified'): return fallback
        positions={e['entry_id']:i for i,e in enumerate(catalog['entries'])}
        prepared=[]
        for group in groups:
            content=[{'type':'text','text':'Reference photo:'}, {'type':'image_url','image_url':{'url':photo_data}}]
            for e in group:
                content.append({'type':'text','text':'Manual position '+str(positions[e['entry_id']])})
                content.extend([{'type':'text','text':'Image ID '+e['entry_id']}, {'type':'image_url','image_url':{'url':image_data(relative_file(root,e['image_file']))}}])
            body={'model':model,'temperature':0,'messages':[{'role':'system','content':'Order ALL supplied catalogue images by visual similarity to the reference photo. Do not identify, name, detect or describe lights or colours. Return ONLY a JSON object with ordered_entry_ids containing every supplied ID exactly once; no other fields.'},{'role':'user','content':content}]}
            if config.get('provider_routing'):
                body['provider']=config['provider_routing']
            encoded=json.dumps(body).encode()
            if len(encoded)>byte_limit: return fallback
            prepared.append((encoded,[e['entry_id'] for e in group]))
        orders=[]
        for encoded,group_ids in prepared:
            req=urllib.request.Request(endpoint,data=encoded,headers=headers,method='POST')
            with urllib.request.build_opener(NoRedirect()).open(req,timeout=30) as response:
                raw=response.read(1024*1024+1)
                if len(raw)>1024*1024: raise ValueError('Response too large')
            answer=json.loads(raw)['choices'][0]['message']['content']
            orders.append(permutation(answer,group_ids))
        # Round-robin of batch ranks: approximate browsing order, NOT a global model ranking.
        order=[o[i] for i in range(max(map(len,orders),default=0)) for o in orders if i<len(o)]
        permutation(json.dumps({'ordered_entry_ids':order}),ids)
        return {'ordered_entry_ids':order,'mode':'similarity_order' if len(orders)==1 else 'batch_similarity_interleaved',
                'all_images_available':True,'global_similarity_rank':len(orders)==1,'batch_count':len(orders)}
    except Exception:
        # Never disclose provider payload, credentials, or photo content in logs.
        return fallback

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('manifest',type=Path); ap.add_argument('photo',type=Path); ap.add_argument('--config',type=Path,required=True); ap.add_argument('--provider',default='none'); ap.add_argument('--consent-provider'); a=ap.parse_args()
    c=yaml.safe_load(a.config.read_text()); d=load_catalog(a.manifest)
    if a.provider not in c['providers']: raise ValueError('Fournisseur inconnu')
    print(json.dumps(rank(d,a.manifest.parent,a.photo,c['providers'][a.provider],a.consent_provider),ensure_ascii=False))
if __name__=='__main__':
    try: main()
    except (ValueError,OSError,KeyError,yaml.YAMLError): raise SystemExit('Tri refusé : catalogue, configuration ou consentement invalide.')
