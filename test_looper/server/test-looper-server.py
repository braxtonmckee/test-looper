#!/usr/bin/env python

import argparse
import json
import traceback
import logging
import os
import signal
import socket
import sys
import threading
import time

import test_looper.core.algebraic_to_json as algebraic_to_json
import test_looper.core.Config as Config
import test_looper.core.machine_management.MachineManagement as MachineManagement

import test_looper.core.source_control.SourceControlFromConfig as SourceControlFromConfig
from test_looper.core.RedisJsonStore import RedisJsonStore
from test_looper.core.InMemoryJsonStore import InMemoryJsonStore
import test_looper.server.TestLooperHttpServer as TestLooperHttpServer
from test_looper.server.TestLooperHttpServerEventLog import TestLooperHttpServerEventLog
import test_looper.server.TestLooperServer as TestLooperServer
import test_looper.data_model.TestManager as TestManager
import test_looper.core.ArtifactStorage as ArtifactStorage

def createArgumentParser():
    parser = argparse.ArgumentParser(
        description="Handles test-looper connections and assign test jobs to loopers."
        )

    parser.add_argument('config',
                        help="Path to configuration file")

    parser.add_argument("-v",
                        "--verbose",
                        action='store_true',
                        help="Set logging level to verbose")

    parser.add_argument("--local",
                        action='store_true',
                        help="Run locally without EC2")

    parser.add_argument("--auth",
                        choices=['full', 'write', 'none'],
                        default='full',
                        help=("Authentication requirements.\n"
                              "Full: no unauthenticated access\n"
                              "Write: must authenticate to write\n"
                              "None: open, unauthenticated access"))

    return parser

def loadConfiguration(configFile):
    with open(configFile, 'r') as fin:
        expanded = os.path.expandvars(fin.read())
        return json.loads(expanded)

def configureLogging(verbose=False):
    if logging.getLogger().handlers:
        logging.getLogger().handlers = []

    loglevel = logging.DEBUG if verbose else logging.INFO
    logging.getLogger().setLevel(loglevel)

    handler = logging.StreamHandler(stream=sys.stderr)

    handler.setLevel(loglevel)
    handler.setFormatter(
        logging.Formatter(
            '%(asctime)s %(levelname)s %(filename)s:%(lineno)s@%(funcName)s %(name)s - %(message)s'
            )
        )
    logging.getLogger().addHandler(handler)

def main():
    parsedArgs = createArgumentParser().parse_args()
    config = loadConfiguration(parsedArgs.config)
    configureLogging(verbose=parsedArgs.verbose)

    config = algebraic_to_json.Encoder().from_json(config, Config.Config)

    if config.server.database.matches.InMemory:
        jsonStore = InMemoryJsonStore()
    else:
        jsonStore = RedisJsonStore(
            port=config.server.database.port or None, 
            db=config.server.database.db
            )

    eventLog = TestLooperHttpServerEventLog(jsonStore)

    src_ctrl = SourceControlFromConfig.getFromConfig(config.server.path_to_local_repos, config.source_control)
    artifact_storage = ArtifactStorage.storageFromConfig(config.artifacts)
    machine_management = MachineManagement.fromConfig(config, src_ctrl, artifact_storage)

    testManager = TestManager.TestManager(src_ctrl, machine_management, jsonStore)
    
    httpServer = TestLooperHttpServer.TestLooperHttpServer(
        config.server_ports,
        config.server,
        testManager,
        machine_management,
        artifact_storage,
        src_ctrl,
        event_log=eventLog
        )

    server = TestLooperServer.TestLooperServer(config.server_ports,
                                               testManager,
                                               httpServer,
                                               machine_management
                                               )

    serverThread = threading.Thread(target=server.runListenLoop)

    def handleStopSignal(signum, _):
        logging.info("Signal received: %s. Stopping service.", signum)
        os._exit(0)

    signal.signal(signal.SIGTERM, handleStopSignal) # handle kill
    signal.signal(signal.SIGINT, handleStopSignal)  # handle ctrl-c

    serverThread.start()

    while True:
        time.sleep(1.0)

if __name__ == "__main__":
    main()
