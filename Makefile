.PHONY: \
	format \
	lint \
	lint-fix \
	test \
	post-change \
	spec-review \
	spec-implementation-review \
	clean-cdk-out \
	prepare-common-lambda-assets \
	cleanup-common-lambda-assets \
	aws-synth \
	aws-diff \
	aws-deploy \
	cdk-synth \
	cdk-diff \
	cdk-deploy \
	local-register \
	local-unregister \
	local-viewer \
	local-job \
	local-trigger \
	manual-feed \
	manual-rss \
	manual-tech-news-feeds \
	manual-product-hunt \
	clean

ARGS ?=

format:
	uv run ruff format .

lint:
	uv run ruff check .

lint-fix:
	uv run ruff check . --fix

test:
	uv run pytest $(ARGS)

post-change:
	${MAKE} format
	${MAKE} lint
	${MAKE} test

spec-review:
	./scripts/spec_review_runner.sh

spec-implementation-review:
	./scripts/spec_implementation_review_runner.sh

prepare-common-lambda-assets:
	@true

cleanup-common-lambda-assets:
	@true

clean-cdk-out:
	rm -rf cdk.out

aws-synth: clean-cdk-out
	uv run python -m nook.deploy.aws.cli synth

aws-diff: clean-cdk-out
	uv run python -m nook.deploy.aws.cli diff

aws-deploy: clean-cdk-out
	uv run python -m nook.deploy.aws.cli deploy

cdk-synth:
	${MAKE} aws-synth

cdk-diff:
	${MAKE} aws-diff

cdk-deploy:
	${MAKE} aws-deploy

local-register:
	uv run python -m nook.deploy.local.cli register

local-unregister:
	uv run python -m nook.deploy.local.cli unregister

local-viewer:
	uv run python -m nook.deploy.local.cli run-viewer

local-job:
	@test -n "$(SERVICE)" || (echo "SERVICE is required" >&2; exit 1)
	uv run python -m nook.deploy.local.cli run-job $(SERVICE)

local-trigger:
	@test -n "$(SERVICE)" || (echo "SERVICE is required, e.g. make local-trigger SERVICE=tech_feed" >&2; exit 1)
	${MAKE} local-job SERVICE="$(SERVICE)"

manual-feed:
	uv run python tests/test_feed.py

manual-rss:
	uv run python tests/test_rss.py

manual-tech-news-feeds:
	uv run python tests/test_tech_news_feeds.py

manual-product-hunt:
	uv run python tests/test_product_hunt.py

clean:
	rm -rf cdk.out
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	find . -type d -name "htmlcov" -exec rm -rf {} +
	find . -type f -name ".coverage" -delete
