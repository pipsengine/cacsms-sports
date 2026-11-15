"""Usage: from apps/api, python scripts/import_standings.py FILE [--dry-run] [--approve]."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.modules.league_intelligence.ingestion import import_document,ImportValidationError

def main():
    p=argparse.ArgumentParser(description='Import authorized league standings JSON')
    p.add_argument('file',type=Path)
    p.add_argument('--dry-run',action='store_true')
    p.add_argument('--approve',action='store_true',help='Only after human evidence review')
    args=p.parse_args()
    if not args.file.is_file() or args.file.stat().st_size>30_000_000:
        raise ImportValidationError('JSON file missing or exceeds 30MB')
    doc=json.loads(args.file.read_text(encoding='utf-8-sig'))
    if args.dry_run:
        print(json.dumps(import_document(None,doc,approve=args.approve,dry_run=True),default=str,indent=2));return
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[3]/'.env',override=False)
    from app.db.base import SessionLocal
    with SessionLocal.begin() as db:
        result=import_document(db,doc,approve=args.approve)
    print(json.dumps(result,indent=2))
if __name__=='__main__':
    try:main()
    except (ImportValidationError,ValueError,OSError) as exc:
        print(f'Import rejected: {exc}',file=sys.stderr);sys.exit(2)
