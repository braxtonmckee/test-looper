"""SequantialFailureRates

Given a sequence of failure rates and counts, estimate a "true" sequence of failure rates given
a bayesian prior that suggests that the probability of a test having a bug is fixed and low.
"""

import math

class SequentialFailureRates(object):
    def __init__(self, probabilityOfChange):
        """Construct a SequantialFailureRates.

        probabilityOfChange - our prior on the chance that the failure rate changes. order of 1/100
        """
        self.failureCountList = []
        self.totalCountList = []
        self.probabilityOfChange = probabilityOfChange
        self.isBreak_ = []
        self.indexOfLastBreak = None

    def __len__(self):
        return len(self.isBreak_)

    def isBreak(self, index):
        if index < 0 or index >= len(self.isBreak_):
            return 0
        return self.isBreak_[index]

    def add(self, failureCount, testCount):
        self.failureCountList.append(failureCount)
        self.totalCountList.append(testCount)
        self.isBreak_.append(0)
        if self.indexOfLastBreak is None:
            self.indexOfLastBreak = 0

        while len(self.failureCountList) - self.indexOfLastBreak > 1:
            if not self.tryToBreak():
                return

    def logLikelihoodImprovementFromAddingBreak(self, breakIndex):
        if breakIndex < 0 or breakIndex >= len(self.isBreak_) or self.isBreak(breakIndex):
            return 0.0

        breakAbove = breakIndex
        breakBelow = breakIndex
        while not self.isBreak(breakAbove) and breakAbove < len(self.isBreak_):
            breakAbove += 1
        while not self.isBreak(breakBelow) and breakBelow > 0:
            breakBelow -= 1

        failsAndCountsBelow = self.failsAndCounts(breakBelow, breakIndex)
        failsAndCountsAbove = self.failsAndCounts(breakIndex, breakAbove)

        logLikelihoodSeparate = self.logLikelihood(*failsAndCountsBelow) + self.logLikelihood(*failsAndCountsAbove)
        logLikelihoodTogether = self.logLikelihood(
            failsAndCountsBelow[0] + failsAndCountsAbove[0],
            failsAndCountsBelow[1] + failsAndCountsAbove[1]
            )

        return logLikelihoodSeparate - logLikelihoodTogether

    def logLikelihoodsAtBreak(self, breakIndex):
        failsAndCountsBelow = self.failsAndCounts(self.indexOfLastBreak, breakIndex)
        failsAndCountsAbove = self.failsAndCounts(breakIndex, len(self.failureCountList))

        logLikelihoodSeparate = self.logLikelihood(*failsAndCountsBelow) + self.logLikelihood(*failsAndCountsAbove)
        logLikelihoodTogether = self.logLikelihood(
            failsAndCountsBelow[0] + failsAndCountsAbove[0],
            failsAndCountsBelow[1] + failsAndCountsAbove[1]
            )

        return (
            logLikelihoodSeparate + math.log(self.probabilityOfChange),
            logLikelihoodTogether,
            self.directionOfChange(failsAndCountsBelow, failsAndCountsAbove)
            )

    def directionOfChange(self, failsAndCountsBelow, failsAndCountsAbove):
        p_below = self.failureProbability(*failsAndCountsBelow)
        p_above = self.failureProbability(*failsAndCountsAbove)
        return cmp(p_below, p_above)

    def tryToBreak(self):
        likelihoodAtBestBreak = None
        bestBreak = None

        for breakpt in range(self.indexOfLastBreak + 1, len(self.failureCountList)):
            withBreak, withoutBreak, direction = self.logLikelihoodsAtBreak(breakpt)

            if withBreak > withoutBreak:
                if likelihoodAtBestBreak is None or withBreak > likelihoodAtBestBreak:
                    likelihoodAtBestBreak = withBreak
                    bestBreak = (breakpt, direction)

        if bestBreak is not None:
            self.breakAt(*bestBreak)
            return True

        return False

    def failsAndCounts(self, indexLow, indexHigh):
        return (
            sum(self.failureCountList[indexLow:indexHigh]),
            sum(self.totalCountList[indexLow:indexHigh])
            )

    def logLikelihood(self, failCount, totalCount):
        p = self.failureProbability(failCount, totalCount)
        #for each failure, we get p. for each success we get 1 - p)
        return 0 if p == 0 else \
            failCount * math.log(p) + (totalCount - failCount) * math.log(1.0 - p)

    def failureProbability(self, failCount, totalCount):
        if failCount == 0 or failCount == totalCount:
            return 0
        return float(failCount) / float(totalCount)

    def breakAt(self, breakpt, direction):
        self.isBreak_[breakpt] = direction
        self.indexOfLastBreak = breakpt

    def breakPairs(self):
        last = 0

        for index in range(len(self.isBreak_)):
            if self.isBreak_[index]:
                yield (last, index)
                last = index

        yield (last, len(self.failureCountList))

    def estimatedProbabilities(self):
        probs = []

        for low, high in self.breakPairs():
            fails, counts = self.failsAndCounts(low, high)
            p = float(fails) / counts
            for ix in range(high - low):
                probs.append(p)

        return probs



