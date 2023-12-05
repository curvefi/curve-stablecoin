# Curve Stablecoin contracts

## Install dependencies using poetry

Installing poetry and all dependencies for tests

```shell
pip install poetry==1.4.1
poetry install
```

Installing specific dependency groups (main/dev(tests)/ape(deploy))

```shell
poetry install --without dev,ape
```

Updating dependencies

```shell
poetry add vyper
poetry add "vyper>=0.3.7,<0.4"
poetry add --group dev "git+https://github.com/vyperlang/titanoboa.git@6ffcfa724023fb2b9f8ed02221c8bcbf4511712c"
```

Removing dependencies

```shell
poetry remove ape-alchemy --group ape
```

## Environment for forked tests

Install env for forked tests

```shell
cd deploy_env
poetry install --sync
cd -
```

Put settings file ("_.env_") into [parent](.) directory.
[Example](./.env-example) defines all required parameters, mainly
external web3 provider.
