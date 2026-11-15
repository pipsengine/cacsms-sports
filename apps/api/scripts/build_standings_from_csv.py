"""Generate an unapproved standings document from an authorized football CSV."""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.modules.league_intelligence.csv_research import build_standings,CSVResearchError
from app.modules.league_intelligence.ingestion import validate_document

def main():
    p=argparse.ArgumentParser()
    p.add_argument('csv',type=Path);p.add_argument('--country',required=True)
    p.add_argument('--competition',required=True);p.add_argument('--season',required=True)
    p.add_argument('--source',required=True);p.add_argument('--source-url',required=True)
    p.add_argument('--as-of',required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--confirm-authorized',action='store_true')
    p.add_argument('--season-start',help='Explicit ISO season start when creating a new season')
    p.add_argument('--season-end',help='Explicit ISO season end when creating a new season')
    args=p.parse_args()
    doc=build_standings(args.csv,sport='Football',country=args.country,
        competition=args.competition,season=args.season,source=args.source,
        source_url=args.source_url,as_of=args.as_of,permitted=args.confirm_authorized,season_start=args.season_start,season_end=args.season_end)
    validate_document(doc)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(doc,indent=2,ensure_ascii=False),encoding='utf-8')
    print(f'Wrote {len(doc["entries"])} provisional standings entries to {args.output}')
if __name__=='__main__':
    try: main()
    except (CSVResearchError,ValueError,OSError) as exc:
        print(f'Error: {exc}',file=sys.stderr);sys.exit(2)
