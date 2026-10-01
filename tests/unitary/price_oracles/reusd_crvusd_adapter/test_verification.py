import importlib.util
import json
import sys
from pathlib import Path

import boa
import pytest
from vyper.cli.vyper_json import compile_json


ROOT = Path(__file__).resolve().parents[4]
SCRIPT = (
    ROOT / "scripts/deploy/llamalend/ethereum/markets/reUSDsfrxUSDLP-crvUSD/verify.py"
)


@pytest.mark.parametrize(
    "source",
    [
        "curve_stablecoin/price_oracles/v2/StableSwapNGLPOracle.vy",
        "curve_stablecoin/price_oracles/v2/adapters/ReusdCrvUSDAdapter.vy",
        "curve_stablecoin/price_oracles/v2/ChainOracle.vy",
        "curve_stablecoin/mpolicies/v2/HyperbolicMP.vy",
    ],
)
def test_verification_input_reproduces_bytecode(source):
    spec = importlib.util.spec_from_file_location("reusd_lp_verify", SCRIPT)
    verify = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verify)
    result = compile_json(verify._build_vyper_json(ROOT / source))
    assert not [e for e in result.get("errors", []) if e["severity"] == "error"]
    contract = result["contracts"][source][Path(source).stem]
    assert bytes.fromhex(contract["evm"]["bytecode"]["object"][2:]) == (
        boa.load_partial(source).compiler_data.bytecode
    )


def test_failed_verification_exits_nonzero(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("reusd_lp_verify", SCRIPT)
    verify = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verify)
    address = str(boa.env.generate_address("contract"))
    report = {
        key: address
        for key in (
            "lp_oracle",
            "reusd_adapter",
            "price_oracle",
            "monetary_policy",
            "controller",
        )
    }
    report["params"] = dict(
        lp_pool=address,
        lp_coin_idx=0,
        agg=address,
        ema_time=866,
        target_utilization=9 * 10**17,
        target_rate=10**9,
        low_ratio=5 * 10**17,
        high_ratio=5 * 10**18,
        rate_shift=0,
    )
    path = tmp_path / "deployment.json"
    path.write_text(json.dumps(report))
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--deployment", str(path)])
    monkeypatch.setenv("ETHERSCAN_API_KEY", "test")
    monkeypatch.setattr(verify, "_get_creation_txhash", lambda *args: None)
    submitted = []

    def submit(*args, **kwargs):
        submitted.append(args)
        raise RuntimeError("verification rejected")

    monkeypatch.setattr(verify, "_submit", submit)
    with pytest.raises(SystemExit, match="4 contract"):
        verify.main()
    assert len(submitted) == 4
    assert submitted[1][4] == ""  # The reUSD adapter has no constructor arguments.
