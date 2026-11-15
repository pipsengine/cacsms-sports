"""Model promotion requires server-computed out-of-sample validation."""
from app.modules.governance.promotion import assess_challenger,calibration_error
from app.modules.prediction.service import FEATURE_NAMES


def artifact(**overrides):
 base={'feature_names':list(FEATURE_NAMES),'coefficients':[.1]*6,'means':[1.]*6,'scales':[1.]*6,'intercept':0.,
       'training_result_before':'2026-01-01T00:00:00+00:00','holdout_first_result':'2026-02-01T00:00:00+00:00',
       'holdout_metrics':{'brier':.20,'log_loss':.60,'sample_size':60},'baseline_metrics':{'brier':.24,'log_loss':.68,'sample_size':60},
       'reliability_bins':[{'count':30,'predicted':.3,'observed':.32},{'count':30,'predicted':.7,'observed':.68}]}
 base.update(overrides);return base


def test_valid_challenger_passes():
 passed,reasons,evidence=assess_challenger(artifact())
 assert passed and not reasons and abs(evidence['calibration_error']-.02)<1e-9


def test_challenger_must_beat_baseline_out_of_sample():
 passed,reasons,_=assess_challenger(artifact(holdout_metrics={'brier':.25,'log_loss':.70,'sample_size':60}))
 assert not passed and 'DOES_NOT_BEAT_BASELINE_OUT_OF_SAMPLE' in reasons


def test_holdout_must_follow_training_chronologically():
 passed,reasons,_=assess_challenger(artifact(holdout_first_result='2025-12-01T00:00:00+00:00'))
 assert not passed and 'HOLDOUT_NOT_OUT_OF_SAMPLE' in reasons


def test_poor_calibration_blocks_promotion():
 bins=[{'count':30,'predicted':.3,'observed':.6},{'count':30,'predicted':.7,'observed':.4}]
 assert calibration_error(bins)>.08
 passed,reasons,_=assess_challenger(artifact(reliability_bins=bins))
 assert not passed and 'CALIBRATION_ERROR_TOO_HIGH' in reasons


def test_self_declared_flags_are_irrelevant():
 passed,reasons,_=assess_challenger(artifact(approved=True,out_of_sample=True,holdout_metrics={'brier':.3,'log_loss':.9,'sample_size':10}))
 assert not passed and 'HOLDOUT_TOO_SMALL' in reasons
