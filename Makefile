.PHONY: all gbench-test clean

all: gbench-test

gbench-test:
	$(MAKE) -C gbench-test run

clean:
	$(MAKE) -C gbench-test clean
