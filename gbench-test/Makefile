.PHONY: all configure build run json results clean

CMAKE ?= cmake
BUILD_DIR ?= ../build/gbench-test
CONFIG ?= Release
JOBS ?= $(shell nproc)
CPU ?= 0

RESULTS_DIR ?= results
SMOKE_RESULT ?= $(RESULTS_DIR)/smoke_bench.json
GBENCH_SMOKE ?= $(BUILD_DIR)/gbench_smoke

all: run

configure:
	$(CMAKE) -S . -B $(BUILD_DIR) -DCMAKE_BUILD_TYPE=$(CONFIG)

build: configure
	$(CMAKE) --build $(BUILD_DIR) -j $(JOBS)

run: build
	taskset -c $(CPU) $(GBENCH_SMOKE)

json: build results
	taskset -c $(CPU) $(GBENCH_SMOKE) --benchmark_format=json --benchmark_out=$(SMOKE_RESULT)

results:
	mkdir -p $(RESULTS_DIR)

clean:
	$(CMAKE) -E rm -rf $(BUILD_DIR)
	$(CMAKE) -E rm -f $(RESULTS_DIR)/*.json $(RESULTS_DIR)/*.csv $(RESULTS_DIR)/*.log

