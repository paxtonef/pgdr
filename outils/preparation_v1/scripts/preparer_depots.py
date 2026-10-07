#!/usr/bin/env python3
"""Clone repositories, verify E9, create a LOCAL branch; never push."""
import argparse, subprocess
from pathlib import Path
REPOS = ('pgdr', 'vehicle-identity-resolver', 'cpl', 'cpl-product-integration')
E9 = '1eff89d2363fd919a015acbc5279b134092b4f04'
def git(*args):
    return subprocess.run(['git', *args], check=True, text=True, capture_output=True).stdout.strip()
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('destination', type=Path); a=ap.parse_args()
    a.destination.mkdir(parents=True,exist_ok=True)
    for repo in REPOS:
        dest=a.destination/repo
        if not dest.exists(): git('clone', f'https://github.com/paxtonef/{repo}.git',str(dest))
        if git('-C',str(dest),'remote','get-url','origin').removesuffix('.git') != f'https://github.com/paxtonef/{repo}':
            raise ValueError(f'{repo}: dépôt inattendu')
        if git('-C',str(dest),'status','--porcelain'): raise ValueError(f'{repo}: modifications locales, arrêt')
        git('-C',str(dest),'fetch','origin')
        if repo=='pgdr':
            git('-C',str(dest),'merge-base','--is-ancestor',E9,'origin/main')
        branch='v1-notice-selection'
        exists=subprocess.run(['git','-C',str(dest),'show-ref','--verify','--quiet',f'refs/heads/{branch}']).returncode==0
        if exists:
            git('-C',str(dest),'merge-base','--is-ancestor','origin/main',branch)
            git('-C',str(dest),'switch',branch)
        else: git('-C',str(dest),'switch','-c',branch,'origin/main')
        print(repo,git('-C',str(dest),'rev-parse','HEAD'))
    print('Branches locales prêtes. Aucun push. GGM : installer depuis votre archive canonique.')
if __name__=='__main__':
    try: main()
    except (ValueError,subprocess.CalledProcessError): raise SystemExit('Préparation arrêtée : dépôt modifié, base divergente ou Git indisponible. Aucun reset automatique.')
