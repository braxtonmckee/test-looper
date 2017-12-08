import unittest
import tempfile
import os
import shutil
import logging
import sys
import simplejson

import test_looper_tests.common as common
import test_looper.data_model.TestManager as TestManager
import test_looper.core.InMemoryJsonStore as InMemoryJsonStore
import test_looper.core.tools.Git as Git
import test_looper.core.ArtifactStorage as ArtifactStorage
import test_looper.core.source_control.ReposOnDisk as ReposOnDisk
import test_looper.core.cloud.MachineInfo as MachineInfo
import test_looper.core.SubprocessRunner as SubprocessRunner
import docker
import threading

own_dir = os.path.split(__file__)[0]

common.configureLogging()

class MockSourceControl:
    def __init__(self):
        self.repos = set()
        self.commit_test_defs = {}
        self.commit_parents = {}
        self.branch_to_commitId = {}

    def listRepos(self):
        return sorted(self.repos)

    def addCommit(self, commitId, parents, testDefs):
        assert len(commitId.split("/")) == 2

        self.repos.add(commitId.split("/")[0])

        for p in parents:
            assert len(p.split("/")) == 2
            assert p.split("/")[0] == commitId.split("/")[0]
            assert p in self.commit_test_defs

        assert commitId not in self.commit_test_defs

        self.commit_test_defs[commitId] = testDefs
        self.commit_parents[commitId] = tuple(parents)

    def setBranch(self, repoAndBranch, commit):
        if commit is None:
            if repoAndBranch in self.branch_to_commitId:
                del sef.branch_to_commitId[repoAndBranch]
        else:
            assert len(repoAndBranch.split("/")) == 2, "not a valid repo/branch name"
            if "/" not in commit:
                commit = repoAndBranch.split("/")[0] + "/" + commit
            assert len(commit.split("/")) == 2, "not a valid commitId"
            
            assert repoAndBranch.split("/")[0] == commit.split("/")[0], "repos dont match"

            self.branch_to_commitId[repoAndBranch] = commit

    def getRepo(self, repoName):
        if repoName in self.repos:
            return MockRepo(self, repoName)

    def listBranches(self):
        return sorted(list(self.branch_to_commitId))

    def refresh(self):
        pass

class MockRepo:
    def __init__(self, source_control, repoName):
        self.source_control = source_control
        self.repoName = repoName

    def hashParentsAndCommitTitleFor(self, commitId):
        if commitId not in self.source_control.commit_parents:
            raise Exception("Can't find %s in %s" % (commitId, self.source_control.commit_parents.keys()))

        return commitId.split("/")[1], [p.split("/")[1] for p in self.source_control.commit_parents[commitId]], "title"

    def commitsLookingBack(self, branchOrHash, depth):
        branchOrHash = self.repoName + "/" + branchOrHash
        branchOrHash = self.source_control.branch_to_commitId.get(branchOrHash, branchOrHash)

        tuples = []

        tuples.append(self.hashParentsAndCommitTitleFor(branchOrHash))

        while len(tuples) < depth and len(tuples[-1][1]):
            firstParent = tuples[-1][1][0]
            tuples.append(self.hashParentsAndCommitTitleFor(self.repoName + "/" + firstParent))

        return tuples
    
    def listBranches(self):
        return sorted([b.split("/")[1] for b in self.source_control.branch_to_commitId if b.startswith(self.repoName + "/")])

    def branchTopCommit(self, branch):
        return self.source_control.branch_to_commitId[self.repoName + "/" + branch].split("/")[1]

    def commitsBetweenBranches(self, branch1, branch2):
        assert False, (branch1, branch2)

    def getTestScriptDefinitionsForCommit(self, commitHash):
        assert "/" not in commitHash
        return self.source_control.commit_test_defs[self.repoName + "/" + commitHash]

basic_yaml_file_repo1 = """
looper_version: 2
environments:
  linux: 
    platform: linux
    image:
      dockerfile: "test_looper/Dockerfile.txt"
    variables:
      ENV_VAR: ENV_VAL
  windows: 
    platform: windows
    image:
      dockerfile: "test_looper/Dockerfile.txt"
    variables:
      ENV_VAR: ENV_VAL
builds:
  build/linux:
    command: "build.sh"
tests:
  test/linux:
    command: "test.sh"
    dependencies:
      build: build/linux
"""
basic_yaml_file_repo2 = """
looper_version: 2
repos:
  child: repo1/c0
environments:
  linux: 
    import: child/linux
  windows: 
    import: child/windows
  test_linux:
    platform: linux
    image:
      dockerfile: "test_looper/Dockerfile.txt"
    variables:
      ENV_VAR: ENV_VAL
  all_linux:
    group: [linux, test_linux]
builds:
  build/all_linux:
    command: "build.sh $TEST_LOOPER_IMPORTS/child"
    dependencies:
      child: child/build/
tests:
  test/all_linux:
    command: "test.sh $TEST_LOOPER_IMPORTS/build"
    dependencies:
      build: build/
"""

class TestManagerTests(unittest.TestCase):
    def get_manager(self):
        manager = TestManager.TestManager(
            MockSourceControl(), 
            InMemoryJsonStore.InMemoryJsonStore(),
            TestManager.TestManagerSettings.Settings(max_test_count=3)
            )

        return manager

    def test_manager_refresh(self):
        manager = self.get_manager()

        manager.source_control.addCommit("repo1/c0", [], basic_yaml_file_repo1)
        manager.source_control.addCommit("repo1/c1", ["repo1/c0"], basic_yaml_file_repo1)
        manager.source_control.addCommit("repo2/c0", [], basic_yaml_file_repo2)
        manager.source_control.addCommit("repo2/c1", ["repo2/c0"], basic_yaml_file_repo2)

        manager.source_control.setBranch("repo1/master", "repo1/c1")
        manager.source_control.setBranch("repo2/master", "repo2/c1")


        ts = [0.0]
        manager.markRepoListDirty(ts[0])


        def consumeAllBackgroundWork():
            while True:
                ts[0] += 1.0
                task = manager.performBackgroundWork(ts[0])
                if task is None:
                    return

        def startAllNewTests():
            tests = []
            while len(tests) < 1000:
                commitNameAndTest = manager.startNewTest("machine", ts[0])

                if commitNameAndTest[0]:
                    tests.append(commitNameAndTest)
                else:
                    return tests
                ts[0] += 1

            assert False

        def doTestsInPhases():
            counts = []

            while True:
                consumeAllBackgroundWork()
                tests = startAllNewTests()
                if not tests:
                    return counts
                counts.append([x[0] + "/" + x[1] for x in tests])

                for _,_,testId in tests:
                    manager.testHeartbeat(testId, ts[0])
                    ts[0] += .1

                for _,_,testId in tests:
                    manager.recordTestResults(True, testId, ts[0])
                    ts[0] += .1

        phases = doTestsInPhases()
        self.assertTrue(len(phases) == 3)
        
        self.assertEqual(sorted(phases[0]), sorted([
            "repo1/c1/build/linux",
            "repo1/c0/build/linux"
            ]))

        self.assertEqual(sorted(phases[1]), sorted([
            "repo2/c1/build/linux",
            "repo2/c0/build/linux",
            "repo1/c1/test/linux",
            "repo1/c0/test/linux",
            "repo1/c1/test/linux",
            "repo1/c0/test/linux",
            "repo1/c1/test/linux",
            "repo1/c0/test/linux"
            ]))
        
        self.assertEqual(sorted(phases[2]), sorted([
            "repo2/c1/test/linux",
            "repo2/c0/test/linux",
            "repo2/c1/test/linux",
            "repo2/c0/test/linux",
            "repo2/c1/test/linux",
            "repo2/c0/test/linux"
            ]))
