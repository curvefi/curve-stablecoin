import os
import boa
import logging
import requests

from web3 import HTTPProvider, Web3
import json

logger = logging.getLogger('warnings')
logger.setLevel(logging.ERROR)

positions = [
    [21758686, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x81e3b8957e9Ab1b3ae1785Fd6ba7B1AcC2173490"],
    [20542247, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x00Fb4599c681CA15FDF1AA537B066630876102aE"],
    [20242554, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x0477011BBb0BD4a6A8a59182FF58dE328E3592a4"],
    [20267600, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x10e50901A9F65629715db45B24e5b047a6F11240"],
    [20665126, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x1C79cb8Ce8C3695ed871E4D4e4519D937630832d"],
    [18818673, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x1CB82662c90260A6Cbe6Ab0B8298a3208B666b91"],
    [20563722, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x1d04Cd3BC5C9EDA103D7Feb2DB72350dB612E99a"],
    [17939156, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x1E268f0802321078A20153EcFA7Be65e4a078C59"],
    [19570343, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x1e42E843e666Fc90844e609Bd66c32E2A2A0d5E8"],
    [21741988, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x201051Ae0FddaC0Ce47B299E4673cAA39f32A961"],
    [19956294, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x2098ed20eD0d7a78023977dDcd33DD8c596D1d03"],
    [21725260, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x20b9Efc68DB884Db2a6f804265f2F6ba611a0F41"],
    [20606655, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x229A72082D79a6FC5EE65BCC9147a5B8501C9016"],
    [21078316, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x23bF6fd9c3Cb027fACd71d052981C3F74E1f1860"],
    [19482899, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x26701C848abf9f2422A1FD5aA9B8b4544328A043"],
    [20480142, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x29D37036C9EE7e76413b93BEEe9e2c1b8E8Ad368"],
    [19650067, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x2F0126966657563C4a376cE43ba43891d7537A32"],
    [21768935, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x314e5699db4756138107AE7d7EeDDf5708583ff5"],
    [18871481, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x3182696B6B106a68a3062a8798183D87f20Ed598"],
    [21498433, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x332192943b3E347c5733924995d3423F26186b5c"],
    [19098969, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x369F54c03447B0f3af7760CE730a1364D1c23e1E"],
    [20223450, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x442ABE3cef7665cEC0E57715EE8BA686762865ae"],
    [21214455, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x4BD46cd07Dbc52805B424CbED5942A0F24E28725"],
    [20159005, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x4Cb43773C56a85991f3201A316C650cA88acC873"],
    [20480142, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x4cC7303602376679a0E69434f3B25703e465F535"],
    [18355636, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x4da79bBf1f9cB0086684E8Eb0fb5e559952Bd0BC"],
    [20694185, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x547E826F342f0355055E9424D5797D5Bc5F73221"],
    [20552973, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x5A684c08261380B91D8976eDB0cabf87744650a5"],
    [19113233, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x5e52b108018Dd567A34b0B403b95cBA848ab974C"],
    [19500711, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x5Eae7CDc3A9F357B1Ca1f4918dB664A9E7CD5FF6"],
    [17940349, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x5fF910c34Db2Ae9Eeee29cf6902197CBC7B6812D"],
    [20111365, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x60Fa6eEf5415aD3a7FbEC63F3419eb5F590b88cb"],
    [18311584, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x6119Fa6C5B18BE03F3b8E408c961E28239A0108C"],
    [19371711, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x63Fe1742192f07D67739cc0f091645a2A50804E1"],
    [18962158, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x654adAa768FD13c3904fD64B56E1d2A530447D47"],
    [20625752, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x65FacE9427f10a7818698de0343201c8e494aCFD"],
    [20768982, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x6690547dA5fcB5d775f18d4473Cd9c05eBFFE545"],
    [18381864, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x6764E71d06f5947784B81718A834afFaf548b5cB"],
    [20285517, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x6943A928EE855BbE7A7F96Dab4178Dfda3fB91e0"],
    [20074413, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x6D1F9CF37Cfb93a2eC0125bA107a251F459cc575"],
    [20472964, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x7021528C73E008E06E7D83a1e0697D0b072F0D0B"],
    [18302049, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x7944642920Df33BAE461f86Aa0cd0b4B8284330E"],
    [20462218, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x794F2331F69f9D276a3A006953669CD2FC23Ab92"],
    [19754870, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x79A47EA2bF6C0f036E8EB1022a7693e2cffD5C50"],
    [19703638, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x7BaE493fb2f56F43cdc535d6Ad6C845f8C2B35e2"],
    [21031734, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x81e3b8957e9Ab1b3ae1785Fd6ba7B1AcC2173490"],
    [19641764, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x83786E8634813DbF45E305bb28B7fCf855D314A7"],
    [17736621, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x83A6851f146A272Ff257afd7509f9747A87FB689"],
    [18136740, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x84834D3B6844E25CE6911a50897EC073Fb489568"],
    [18087987, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x8a625BF21c01A83d93D1175556Ef3aF76b862c83"],
    [20403708, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x8d46f6E3B726D17139238d8d1d372838Be422dBE"],
    [20692603, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x8E53B23D255208CBF2Ff86Eb282f30CEB61539ED"],
    [20710519, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x8ec6A1e5Af3656b78f99D21687422E237Df6e384"],
    [20128026, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x8Fee6B44B975D9BF99728Ae22E1FEDEc38De2Bcf"],
    [20816722, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x92957DC2Fc5c1E40b117EB1f9515acb601d6A1f1"],
    [19476963, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x93285233955DdD615f1bAEaa7825D662152c6F24"],
    [18399734, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x944cF2acB0DB10d0863fE45C4916B2fd7005C6a4"],
    [20699769, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0x9C398b892B492787E79FB998078b56Ba0F6A250B"],
    [21650034, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xA2471055588395Dc8A88614dA1CeE0Ce2512f85F"],
    [20287898, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xA4B738b8E5dbb479FdB7489958F9dD5569FbbCEa"],
    [20456791, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xa8c76bE1297B81b0CE3874D7E8B4a44F7d1f7E0b"],
    [18296083, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xAa9E20bAb58d013220D632874e9Fe44F8F971e4d"],
    [19439013, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xAb40e16d0156D14169D0feF043B3f2FcC6A43fD0"],
    [21200117, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xAD60032Bb3fB14b7d863877B5C2FB9833913919C"],
    [19641764, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xB221963CAD5856c657647D7126A6Fe6A47CaC773"],
    [21379122, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xb29E391A1124Ab6c6e68A210cdFC5824c8E2A4B5"],
    [20748706, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xb3268b55dB5D25A88BAfFa261977c1F1C8e989b8"],
    [20458453, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xb820Fd41dbFEd079Ea2F612399361E5033Dd7af7"],
    [19472215, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xBaF17D8126eFB243F56B9cF814aBAB6B5d34AE37"],
    [18147390, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xBbF31ae642CceB471380D64D987f925aFcF6C32a"],
    [18796120, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xC3b876976D58dD9c2e8ab8ce0446C1D5eD8bF55c"],
    [18844809, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xc3C6B0C4F9C3871b072DC087336A5391f9BF3c07"],
    [20112551, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xC4aFfC415D30b7518c724114F6374172F97F4C0f"],
    [18621189, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xC773B66E3766FF7515bbA8906f99E4BfBA958D65"],
    [21472162, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xc99989c2913BF8Cf1978E6fd7fcDb587a4D3fd3b"],
    [18392585, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xCD67353EcC3755C1f4f3976a1e1929fB5e61aa33"],
    [19683394, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xce6C68Bf0567F14a0FB43D85B707d5EaFdA8027A"],
    [21017392, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xCf115cBA7638FFDe4d32E9fD8d0A70d131b42717"],
    [19104897, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xD3Dd68F794174cbadf0dA25fb15cdf9D4D673D45"],
    [18809168, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xd416B5510645b532E1414fa71F4aD895abDc4D44"],
    [18819857, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xd5d7d4bA0f5FBCC8c2c04D14EcE01dC6e6261DC0"],
    [18816304, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xD6AF98Abce0f9260Fcd2C1c49884413fcDC60F6F"],
    [20283113, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xd87EcC6C74F486B044824a222326A96F696fCfA2"],
    [18356829, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xD9F4DdA53ABc0ad6eae07eD2e47b3108c3a131b8"],
    [20991096, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xda139B194Fd979622DeA0381F6D206790B0D6F41"],
    [18215044, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xE408D65d495c567aB246E7c90F11d15d96c1738D"],
    [20467001, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xe4727db0D9eF3cA11b9D177c2E92f63b512993A5"],
    [20461028, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xe77Adf593302A6524D054A27E886021c2cEf8c0B"],
    [19491216, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xE9e2aa87f02e92c33b7A4C705196c9218b11d2e5"],
    [19444955, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xea3F9b017C6b811B0a8Ca642346Bd805D936Fce4"],
    [20055315, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xebdeff4D7053bF84262D2f9FC261a900c4323d83"],
    [19889538, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xEC3c1940d88B8875b39b41e6D023026da500D4bB"],
    [18817492, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xf11F0Add0e8E4ee208104d8264fcf1B69C4CeAfc"],
    [18204326, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xF9605D8c4c987d7Cb32D0d11FbCb8EeeB1B22D5d"],
    [20827471, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xfa8b48009A1749442566882B814927B239bE131F"],
    [20480137, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xfBB4D0C7282E3cfB1F1243345F245188b17cC2Fd"],
    [21379079, "0xA920De414eA4Ab66b97dA1bFE9e6EcA7d4219635", "0xfea6e4c830210361aBA38A07828B73686643f411"],
]

url = os.getenv("WEB3_PROVIDER_URL")

abi="""[{"name":"UserState","inputs":[{"name":"user","type":"address","indexed":true},{"name":"collateral","type":"uint256","indexed":false},{"name":"debt","type":"uint256","indexed":false},{"name":"n1","type":"int256","indexed":false},{"name":"n2","type":"int256","indexed":false},{"name":"liquidation_discount","type":"uint256","indexed":false}],"anonymous":false,"type":"event"},{"name":"Borrow","inputs":[{"name":"user","type":"address","indexed":true},{"name":"collateral_increase","type":"uint256","indexed":false},{"name":"loan_increase","type":"uint256","indexed":false}],"anonymous":false,"type":"event"},{"name":"Repay","inputs":[{"name":"user","type":"address","indexed":true},{"name":"collateral_decrease","type":"uint256","indexed":false},{"name":"loan_decrease","type":"uint256","indexed":false}],"anonymous":false,"type":"event"},{"name":"RemoveCollateral","inputs":[{"name":"user","type":"address","indexed":true},{"name":"collateral_decrease","type":"uint256","indexed":false}],"anonymous":false,"type":"event"},{"name":"Liquidate","inputs":[{"name":"liquidator","type":"address","indexed":true},{"name":"user","type":"address","indexed":true},{"name":"collateral_received","type":"uint256","indexed":false},{"name":"stablecoin_received","type":"uint256","indexed":false},{"name":"debt","type":"uint256","indexed":false}],"anonymous":false,"type":"event"},{"name":"SetMonetaryPolicy","inputs":[{"name":"monetary_policy","type":"address","indexed":false}],"anonymous":false,"type":"event"},{"name":"SetBorrowingDiscounts","inputs":[{"name":"loan_discount","type":"uint256","indexed":false},{"name":"liquidation_discount","type":"uint256","indexed":false}],"anonymous":false,"type":"event"},{"name":"CollectFees","inputs":[{"name":"amount","type":"uint256","indexed":false},{"name":"new_supply","type":"uint256","indexed":false}],"anonymous":false,"type":"event"},{"stateMutability":"nonpayable","type":"constructor","inputs":[{"name":"collateral_token","type":"address"},{"name":"monetary_policy","type":"address"},{"name":"loan_discount","type":"uint256"},{"name":"liquidation_discount","type":"uint256"},{"name":"amm","type":"address"}],"outputs":[]},{"stateMutability":"payable","type":"fallback"},{"stateMutability":"view","type":"function","name":"factory","inputs":[],"outputs":[{"name":"","type":"address"}]},{"stateMutability":"view","type":"function","name":"amm","inputs":[],"outputs":[{"name":"","type":"address"}]},{"stateMutability":"view","type":"function","name":"collateral_token","inputs":[],"outputs":[{"name":"","type":"address"}]},{"stateMutability":"view","type":"function","name":"debt","inputs":[{"name":"user","type":"address"}],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"loan_exists","inputs":[{"name":"user","type":"address"}],"outputs":[{"name":"","type":"bool"}]},{"stateMutability":"view","type":"function","name":"total_debt","inputs":[],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"max_borrowable","inputs":[{"name":"collateral","type":"uint256"},{"name":"N","type":"uint256"}],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"max_borrowable","inputs":[{"name":"collateral","type":"uint256"},{"name":"N","type":"uint256"},{"name":"current_debt","type":"uint256"}],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"min_collateral","inputs":[{"name":"debt","type":"uint256"},{"name":"N","type":"uint256"}],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"calculate_debt_n1","inputs":[{"name":"collateral","type":"uint256"},{"name":"debt","type":"uint256"},{"name":"N","type":"uint256"}],"outputs":[{"name":"","type":"int256"}]},{"stateMutability":"payable","type":"function","name":"create_loan","inputs":[{"name":"collateral","type":"uint256"},{"name":"debt","type":"uint256"},{"name":"N","type":"uint256"}],"outputs":[]},{"stateMutability":"payable","type":"function","name":"create_loan_extended","inputs":[{"name":"collateral","type":"uint256"},{"name":"debt","type":"uint256"},{"name":"N","type":"uint256"},{"name":"callbacker","type":"address"},{"name":"callback_args","type":"uint256[]"}],"outputs":[]},{"stateMutability":"payable","type":"function","name":"add_collateral","inputs":[{"name":"collateral","type":"uint256"}],"outputs":[]},{"stateMutability":"payable","type":"function","name":"add_collateral","inputs":[{"name":"collateral","type":"uint256"},{"name":"_for","type":"address"}],"outputs":[]},{"stateMutability":"nonpayable","type":"function","name":"remove_collateral","inputs":[{"name":"collateral","type":"uint256"}],"outputs":[]},{"stateMutability":"nonpayable","type":"function","name":"remove_collateral","inputs":[{"name":"collateral","type":"uint256"},{"name":"use_eth","type":"bool"}],"outputs":[]},{"stateMutability":"payable","type":"function","name":"borrow_more","inputs":[{"name":"collateral","type":"uint256"},{"name":"debt","type":"uint256"}],"outputs":[]},{"stateMutability":"nonpayable","type":"function","name":"repay","inputs":[{"name":"_d_debt","type":"uint256"}],"outputs":[]},{"stateMutability":"nonpayable","type":"function","name":"repay","inputs":[{"name":"_d_debt","type":"uint256"},{"name":"_for","type":"address"}],"outputs":[]},{"stateMutability":"nonpayable","type":"function","name":"repay","inputs":[{"name":"_d_debt","type":"uint256"},{"name":"_for","type":"address"},{"name":"max_active_band","type":"int256"}],"outputs":[]},{"stateMutability":"nonpayable","type":"function","name":"repay","inputs":[{"name":"_d_debt","type":"uint256"},{"name":"_for","type":"address"},{"name":"max_active_band","type":"int256"},{"name":"use_eth","type":"bool"}],"outputs":[]},{"stateMutability":"nonpayable","type":"function","name":"repay_extended","inputs":[{"name":"callbacker","type":"address"},{"name":"callback_args","type":"uint256[]"}],"outputs":[]},{"stateMutability":"view","type":"function","name":"health_calculator","inputs":[{"name":"user","type":"address"},{"name":"d_collateral","type":"int256"},{"name":"d_debt","type":"int256"},{"name":"full","type":"bool"}],"outputs":[{"name":"","type":"int256"}]},{"stateMutability":"view","type":"function","name":"health_calculator","inputs":[{"name":"user","type":"address"},{"name":"d_collateral","type":"int256"},{"name":"d_debt","type":"int256"},{"name":"full","type":"bool"},{"name":"N","type":"uint256"}],"outputs":[{"name":"","type":"int256"}]},{"stateMutability":"nonpayable","type":"function","name":"liquidate","inputs":[{"name":"user","type":"address"},{"name":"min_x","type":"uint256"}],"outputs":[]},{"stateMutability":"nonpayable","type":"function","name":"liquidate","inputs":[{"name":"user","type":"address"},{"name":"min_x","type":"uint256"},{"name":"use_eth","type":"bool"}],"outputs":[]},{"stateMutability":"nonpayable","type":"function","name":"liquidate_extended","inputs":[{"name":"user","type":"address"},{"name":"min_x","type":"uint256"},{"name":"frac","type":"uint256"},{"name":"use_eth","type":"bool"},{"name":"callbacker","type":"address"},{"name":"callback_args","type":"uint256[]"}],"outputs":[]},{"stateMutability":"view","type":"function","name":"tokens_to_liquidate","inputs":[{"name":"user","type":"address"}],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"tokens_to_liquidate","inputs":[{"name":"user","type":"address"},{"name":"frac","type":"uint256"}],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"health","inputs":[{"name":"user","type":"address"}],"outputs":[{"name":"","type":"int256"}]},{"stateMutability":"view","type":"function","name":"health","inputs":[{"name":"user","type":"address"},{"name":"full","type":"bool"}],"outputs":[{"name":"","type":"int256"}]},{"stateMutability":"view","type":"function","name":"users_to_liquidate","inputs":[],"outputs":[{"name":"","type":"tuple[]","components":[{"name":"user","type":"address"},{"name":"x","type":"uint256"},{"name":"y","type":"uint256"},{"name":"debt","type":"uint256"},{"name":"health","type":"int256"}]}]},{"stateMutability":"view","type":"function","name":"users_to_liquidate","inputs":[{"name":"_from","type":"uint256"}],"outputs":[{"name":"","type":"tuple[]","components":[{"name":"user","type":"address"},{"name":"x","type":"uint256"},{"name":"y","type":"uint256"},{"name":"debt","type":"uint256"},{"name":"health","type":"int256"}]}]},{"stateMutability":"view","type":"function","name":"users_to_liquidate","inputs":[{"name":"_from","type":"uint256"},{"name":"_limit","type":"uint256"}],"outputs":[{"name":"","type":"tuple[]","components":[{"name":"user","type":"address"},{"name":"x","type":"uint256"},{"name":"y","type":"uint256"},{"name":"debt","type":"uint256"},{"name":"health","type":"int256"}]}]},{"stateMutability":"view","type":"function","name":"amm_price","inputs":[],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"user_prices","inputs":[{"name":"user","type":"address"}],"outputs":[{"name":"","type":"uint256[2]"}]},{"stateMutability":"view","type":"function","name":"user_state","inputs":[{"name":"user","type":"address"}],"outputs":[{"name":"","type":"uint256[4]"}]},{"stateMutability":"nonpayable","type":"function","name":"set_amm_fee","inputs":[{"name":"fee","type":"uint256"}],"outputs":[]},{"stateMutability":"nonpayable","type":"function","name":"set_amm_admin_fee","inputs":[{"name":"fee","type":"uint256"}],"outputs":[]},{"stateMutability":"nonpayable","type":"function","name":"set_monetary_policy","inputs":[{"name":"monetary_policy","type":"address"}],"outputs":[]},{"stateMutability":"nonpayable","type":"function","name":"set_borrowing_discounts","inputs":[{"name":"loan_discount","type":"uint256"},{"name":"liquidation_discount","type":"uint256"}],"outputs":[]},{"stateMutability":"nonpayable","type":"function","name":"set_callback","inputs":[{"name":"cb","type":"address"}],"outputs":[]},{"stateMutability":"view","type":"function","name":"admin_fees","inputs":[],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"nonpayable","type":"function","name":"collect_fees","inputs":[],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"liquidation_discounts","inputs":[{"name":"arg0","type":"address"}],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"loans","inputs":[{"name":"arg0","type":"uint256"}],"outputs":[{"name":"","type":"address"}]},{"stateMutability":"view","type":"function","name":"loan_ix","inputs":[{"name":"arg0","type":"address"}],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"n_loans","inputs":[],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"minted","inputs":[],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"redeemed","inputs":[],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"monetary_policy","inputs":[],"outputs":[{"name":"","type":"address"}]},{"stateMutability":"view","type":"function","name":"liquidation_discount","inputs":[],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"loan_discount","inputs":[],"outputs":[{"name":"","type":"uint256"}]}]"""
amm_abi="""[{"name":"TokenExchange","inputs":[{"name":"buyer","type":"address","indexed":true},{"name":"sold_id","type":"uint256","indexed":false},{"name":"tokens_sold","type":"uint256","indexed":false},{"name":"bought_id","type":"uint256","indexed":false},{"name":"tokens_bought","type":"uint256","indexed":false}],"anonymous":false,"type":"event"},{"name":"Deposit","inputs":[{"name":"provider","type":"address","indexed":true},{"name":"amount","type":"uint256","indexed":false},{"name":"n1","type":"int256","indexed":false},{"name":"n2","type":"int256","indexed":false}],"anonymous":false,"type":"event"},{"name":"Withdraw","inputs":[{"name":"provider","type":"address","indexed":true},{"name":"amount_borrowed","type":"uint256","indexed":false},{"name":"amount_collateral","type":"uint256","indexed":false}],"anonymous":false,"type":"event"},{"name":"SetRate","inputs":[{"name":"rate","type":"uint256","indexed":false},{"name":"rate_mul","type":"uint256","indexed":false},{"name":"time","type":"uint256","indexed":false}],"anonymous":false,"type":"event"},{"name":"SetFee","inputs":[{"name":"fee","type":"uint256","indexed":false}],"anonymous":false,"type":"event"},{"name":"SetAdminFee","inputs":[{"name":"fee","type":"uint256","indexed":false}],"anonymous":false,"type":"event"},{"stateMutability":"nonpayable","type":"constructor","inputs":[{"name":"_borrowed_token","type":"address"},{"name":"_borrowed_precision","type":"uint256"},{"name":"_collateral_token","type":"address"},{"name":"_collateral_precision","type":"uint256"},{"name":"_A","type":"uint256"},{"name":"_sqrt_band_ratio","type":"uint256"},{"name":"_log_A_ratio","type":"int256"},{"name":"_base_price","type":"uint256"},{"name":"fee","type":"uint256"},{"name":"admin_fee","type":"uint256"},{"name":"_price_oracle_contract","type":"address"}],"outputs":[]},{"stateMutability":"nonpayable","type":"function","name":"set_admin","inputs":[{"name":"_admin","type":"address"}],"outputs":[]},{"stateMutability":"pure","type":"function","name":"coins","inputs":[{"name":"i","type":"uint256"}],"outputs":[{"name":"","type":"address"}]},{"stateMutability":"view","type":"function","name":"price_oracle","inputs":[],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"dynamic_fee","inputs":[],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"get_rate_mul","inputs":[],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"get_base_price","inputs":[],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"p_current_up","inputs":[{"name":"n","type":"int256"}],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"p_current_down","inputs":[{"name":"n","type":"int256"}],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"p_oracle_up","inputs":[{"name":"n","type":"int256"}],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"p_oracle_down","inputs":[{"name":"n","type":"int256"}],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"get_p","inputs":[],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"read_user_tick_numbers","inputs":[{"name":"user","type":"address"}],"outputs":[{"name":"","type":"int256[2]"}]},{"stateMutability":"view","type":"function","name":"can_skip_bands","inputs":[{"name":"n_end","type":"int256"}],"outputs":[{"name":"","type":"bool"}]},{"stateMutability":"view","type":"function","name":"active_band_with_skip","inputs":[],"outputs":[{"name":"","type":"int256"}]},{"stateMutability":"view","type":"function","name":"has_liquidity","inputs":[{"name":"user","type":"address"}],"outputs":[{"name":"","type":"bool"}]},{"stateMutability":"nonpayable","type":"function","name":"deposit_range","inputs":[{"name":"user","type":"address"},{"name":"amount","type":"uint256"},{"name":"n1","type":"int256"},{"name":"n2","type":"int256"}],"outputs":[]},{"stateMutability":"nonpayable","type":"function","name":"withdraw","inputs":[{"name":"user","type":"address"},{"name":"frac","type":"uint256"}],"outputs":[{"name":"","type":"uint256[2]"}]},{"stateMutability":"view","type":"function","name":"get_dy","inputs":[{"name":"i","type":"uint256"},{"name":"j","type":"uint256"},{"name":"in_amount","type":"uint256"}],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"get_dxdy","inputs":[{"name":"i","type":"uint256"},{"name":"j","type":"uint256"},{"name":"in_amount","type":"uint256"}],"outputs":[{"name":"","type":"uint256"},{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"get_dx","inputs":[{"name":"i","type":"uint256"},{"name":"j","type":"uint256"},{"name":"out_amount","type":"uint256"}],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"get_dydx","inputs":[{"name":"i","type":"uint256"},{"name":"j","type":"uint256"},{"name":"out_amount","type":"uint256"}],"outputs":[{"name":"","type":"uint256"},{"name":"","type":"uint256"}]},{"stateMutability":"nonpayable","type":"function","name":"exchange","inputs":[{"name":"i","type":"uint256"},{"name":"j","type":"uint256"},{"name":"in_amount","type":"uint256"},{"name":"min_amount","type":"uint256"}],"outputs":[{"name":"","type":"uint256[2]"}]},{"stateMutability":"nonpayable","type":"function","name":"exchange","inputs":[{"name":"i","type":"uint256"},{"name":"j","type":"uint256"},{"name":"in_amount","type":"uint256"},{"name":"min_amount","type":"uint256"},{"name":"_for","type":"address"}],"outputs":[{"name":"","type":"uint256[2]"}]},{"stateMutability":"nonpayable","type":"function","name":"exchange_dy","inputs":[{"name":"i","type":"uint256"},{"name":"j","type":"uint256"},{"name":"out_amount","type":"uint256"},{"name":"max_amount","type":"uint256"}],"outputs":[{"name":"","type":"uint256[2]"}]},{"stateMutability":"nonpayable","type":"function","name":"exchange_dy","inputs":[{"name":"i","type":"uint256"},{"name":"j","type":"uint256"},{"name":"out_amount","type":"uint256"},{"name":"max_amount","type":"uint256"},{"name":"_for","type":"address"}],"outputs":[{"name":"","type":"uint256[2]"}]},{"stateMutability":"view","type":"function","name":"get_y_up","inputs":[{"name":"user","type":"address"}],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"get_x_down","inputs":[{"name":"user","type":"address"}],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"get_sum_xy","inputs":[{"name":"user","type":"address"}],"outputs":[{"name":"","type":"uint256[2]"}]},{"stateMutability":"view","type":"function","name":"get_xy","inputs":[{"name":"user","type":"address"}],"outputs":[{"name":"","type":"uint256[][2]"}]},{"stateMutability":"view","type":"function","name":"get_amount_for_price","inputs":[{"name":"p","type":"uint256"}],"outputs":[{"name":"","type":"uint256"},{"name":"","type":"bool"}]},{"stateMutability":"nonpayable","type":"function","name":"set_rate","inputs":[{"name":"rate","type":"uint256"}],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"nonpayable","type":"function","name":"set_fee","inputs":[{"name":"fee","type":"uint256"}],"outputs":[]},{"stateMutability":"nonpayable","type":"function","name":"set_admin_fee","inputs":[{"name":"fee","type":"uint256"}],"outputs":[]},{"stateMutability":"nonpayable","type":"function","name":"reset_admin_fees","inputs":[],"outputs":[]},{"stateMutability":"nonpayable","type":"function","name":"set_callback","inputs":[{"name":"liquidity_mining_callback","type":"address"}],"outputs":[]},{"stateMutability":"view","type":"function","name":"admin","inputs":[],"outputs":[{"name":"","type":"address"}]},{"stateMutability":"view","type":"function","name":"A","inputs":[],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"fee","inputs":[],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"admin_fee","inputs":[],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"rate","inputs":[],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"active_band","inputs":[],"outputs":[{"name":"","type":"int256"}]},{"stateMutability":"view","type":"function","name":"min_band","inputs":[],"outputs":[{"name":"","type":"int256"}]},{"stateMutability":"view","type":"function","name":"max_band","inputs":[],"outputs":[{"name":"","type":"int256"}]},{"stateMutability":"view","type":"function","name":"admin_fees_x","inputs":[],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"admin_fees_y","inputs":[],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"price_oracle_contract","inputs":[],"outputs":[{"name":"","type":"address"}]},{"stateMutability":"view","type":"function","name":"bands_x","inputs":[{"name":"arg0","type":"int256"}],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"bands_y","inputs":[{"name":"arg0","type":"int256"}],"outputs":[{"name":"","type":"uint256"}]},{"stateMutability":"view","type":"function","name":"liquidity_mining_callback","inputs":[],"outputs":[{"name":"","type":"address"}]}]"""


def test_position(position, frac):
    block_number = position[0]
    controller_address = position[1]
    user = position[2]

    block = json.loads(Web3.to_json(Web3(HTTPProvider(url)).eth.get_block(block_number)))

    coin = f"ethereum:0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
    prices_url = f"https://coins.llama.fi/prices/historical/{block['timestamp']}/{coin}"
    resp = requests.get(prices_url)
    spot_price = resp.json()["coins"][coin]["price"]

    boa.fork(url, block_identifier=block_number, allow_dirty=True)
    controller = boa.loads_abi(abi, name="Controller").at(controller_address)
    amm = boa.loads_abi(amm_abi, name="AMM").at(controller.amm())

    # collateral, stablecoin, debt, N
    user_state = controller.user_state(user)
    health = controller.health(user)
    x_down = amm.get_x_down(user)
    ratio = x_down / user_state[2]

    t = f"User: {user}, block: {block_number}, ratio: {ratio}"
    t += '\n' +  (f"user state: health: {health * 100 / 1e18}, collateral: {user_state[0] / 1e18}, "
          f"stablecoin: {user_state[1] / 1e18}, debt: {user_state[2] / 1e18}, ratio: {ratio}")

    stablecoin = boa.load_partial("contracts/Stablecoin.vy").at("0xf939E0A03FB07F59A73314E73794Be0E57ac1b4E")
    assert stablecoin.balanceOf(controller_address) > user_state[2]
    stablecoin.transfer(user, user_state[2], sender=controller_address)
    stablecoin.approve(controller_address, 2**256-1, sender=user)
    assert stablecoin.balanceOf(user) >= user_state[2]

    controller.liquidate_extended(user, 0, int(frac * 10**18), False, "0x0000000000000000000000000000000000000000", [], sender=user)

    user_state2 = controller.user_state(user)
    debt_repayed = (user_state[2] - user_state2[2]) - (user_state[1] - user_state2[1])
    total_surplus = int(debt_repayed * (ratio - 1))
    collateral_used = (user_state[0] - user_state2[0])
    frac_price = (debt_repayed * ratio) / collateral_used
    spot_surplus = (collateral_used * spot_price - debt_repayed)
    health2 = controller.health(user)
    t += '\n' + (f"total sulprus: {total_surplus / 1e18}, spot_surplus: {spot_surplus / 1e18}, spot_price: {spot_price}, frac_price: {frac_price},"
                 f" liquidator_profit:{(spot_surplus - total_surplus) / 1e18}, {(spot_surplus - total_surplus) * 100 / user_state[2]} % of position")
    t += '\n' + (f"user state after part liq: health: {health2 * 100 / 1e18}, collateral: {user_state2[0] / 1e18}, "
          f"stablecoin: {user_state2[1] / 1e18}, debt: {user_state2[2] / 1e18}")

    controller.repay(total_surplus, sender=user)
    health3 = controller.health(user)
    user_state3 = controller.user_state(user)
    t += '\n' + (f"user state after repay: health: {health3 * 100 / 1e18}, collateral: {user_state3[0] / 1e18}, "
          f"stablecoin: {user_state3[1] / 1e18}, debt: {user_state3[2] / 1e18}")

    print(t)

    return t


res = ""

for position in positions:
    try:
        res += test_position(position, 0.05) + '\n' + "-----------------------------" + "\n"
    except KeyboardInterrupt:
        break
    except:
        continue

with open('./test_frac5.txt', 'w') as f:
    f.write(res)
