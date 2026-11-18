"""Default to review-only; explicit application requires a named review reference."""
import argparse
import json
import os
import sys
from run_remediation_checks import ROOT, local_config

os.environ.update(local_config())
sys.path[:0] = [str(ROOT), str(ROOT / 'apps/api')]
from app.db.base import SessionLocal
from app.modules.governance.reconciliation import review, reconcile_labels

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply-model')
    parser.add_argument('--review-reference')
    parser.add_argument('--reviewer')
    args = parser.parse_args()
    if args.apply_model:
        if not args.review_reference or not args.reviewer: parser.error('Application requires --review-reference and --reviewer')
        with SessionLocal.begin() as db:
            result = reconcile_labels(db, args.apply_model, actor=args.reviewer, review_reference=args.review_reference)
    else:
        with SessionLocal() as db: result = review(db)
    print(json.dumps(result, indent=2))
