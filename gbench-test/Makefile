.PHONY: all configure build run run-smoke run-fma-register-peak json json-smoke json-fma-register-peak report report-smoke report-fma-register-peak results clean

CMAKE ?= cmake
BUILD_DIR ?= build
CONFIG ?= Release
JOBS ?= $(shell nproc)
CPU ?= 0

RESULTS_DIR ?= results
SMOKE_RESULT ?= $(RESULTS_DIR)/smoke_bench.json
SMOKE_REPORT ?= $(RESULTS_DIR)/smoke_bench.md
FMA_REGISTER_PEAK_RESULT ?= $(RESULTS_DIR)/fma_register_peak_bench.json
FMA_REGISTER_PEAK_REPORT ?= $(RESULTS_DIR)/fma_register_peak_bench.md
GBENCH_SMOKE ?= $(BUILD_DIR)/gbench_smoke
FMA_REGISTER_PEAK_BENCH ?= $(BUILD_DIR)/fma_register_peak_bench

all: run

configure:
	$(CMAKE) -S . -B $(BUILD_DIR) -DCMAKE_BUILD_TYPE=$(CONFIG)

build: configure
	$(CMAKE) --build $(BUILD_DIR) -j $(JOBS)

run: run-smoke run-fma-register-peak

run-smoke: build
	taskset -c $(CPU) $(GBENCH_SMOKE)

run-fma-register-peak: build
	taskset -c $(CPU) $(FMA_REGISTER_PEAK_BENCH)

json: json-smoke json-fma-register-peak

json-smoke: build results
	taskset -c $(CPU) $(GBENCH_SMOKE) --benchmark_format=json --benchmark_out=$(SMOKE_RESULT)

json-fma-register-peak: build results
	taskset -c $(CPU) $(FMA_REGISTER_PEAK_BENCH) --benchmark_format=json --benchmark_out=$(FMA_REGISTER_PEAK_RESULT)

report: report-smoke report-fma-register-peak

report-smoke: json-smoke
	python3 scripts/gbench_json_to_md.py $(SMOKE_RESULT) $(SMOKE_REPORT)

report-fma-register-peak: json-fma-register-peak
	python3 scripts/gbench_json_to_md.py $(FMA_REGISTER_PEAK_RESULT) $(FMA_REGISTER_PEAK_REPORT)

results:
	mkdir -p $(RESULTS_DIR)

clean:
	$(CMAKE) -E rm -rf $(BUILD_DIR)
	$(CMAKE) -E rm -f $(RESULTS_DIR)/*.json $(RESULTS_DIR)/*.csv $(RESULTS_DIR)/*.log $(RESULTS_DIR)/*.md
