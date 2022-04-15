import os
from Transaction import Transaction
import Lock
import LockTable
import constants
from Command import Command
from graph import Graph
from collections import defaultdict


class TransactionManager:
    """
    Responsible for processing transactions. Detects deadlock and resolves it.
    Makes calls to site manager to release locks when transaction aborts or is committed.
    Stores:
        transactionDict : dictionary of transactions
        locktable : copy of locktable
        siteManager: global site manager instance
        graph: directed graph that is used for cycle detection
        waitingTransactions: dictionary of dictionaries the operation it needs to do and is waiting to perform
        blockedQueue: dictionary of dictionaries that stores transaction blocked and
                            the transaction its waiting for along with the operation it needs to do
        abortedTransaction : dictionary of all aborted transactions

    Authors: Ishita Gangal and Divya Juneja
    Date: 18th November, 2019
    """
    def __init__(self, lockTable, siteManager):
        self.transactionsDict = dict()
        self.lockTable = lockTable
        self.siteManager = siteManager
        self.abortedTransactions = dict()
        self.graph = Graph()
        self.killTransaction = None

        self.waitingTransactions = defaultdict(dict)
        self.killT = None
        self.blockedQueue = defaultdict(dict)
        self.currentTime = 0

    def mainTransactionManager(self, command, time):
        """
        Main method of transaction manager, calls readVariable(), writeVariable(), endTransaction()
        Initializes read only transaction or a normal transaction when they begin,
        creates a new Transaction instance
        Calls function to check if there is a deadlock in blockedQueue or the graph
        Aborts appropriate transaction if there is a deadlock
        :param command: transaction that is being executed/has been read
        :param time: used for startTime of transaction
        """
        typeOfTransaction = command.transactionType
        transactionParams = list(command.get_transactionParameters())
        self.currentTime +=1
        self.checkAbortedTransaction()
        self.changeStateFromBlockedToWaiting()
        self.tryToExecuteWaitingTransactions()

        if typeOfTransaction in [constants.BEGIN, constants.READ_ONLY, constants.WRITE, constants.READ]:
            transactionName = str(transactionParams[0])
            tId = transactionName[1:]
            if typeOfTransaction == constants.BEGIN:
                print("Starting Transaction " + transactionName)
                self.transactionsDict[transactionName] = Transaction(tId, transactionName, self.currentTime)
            elif typeOfTransaction == constants.READ_ONLY:
                print("Starting Read Only Transaction " + transactionName)
                self.transactionsDict[transactionName] = Transaction(tId, transactionName, self.currentTime, True)
                self.transactionsDict[transactionName].writeVar = self.siteManager.getVariablesValues()
            elif typeOfTransaction == constants.WRITE:
                self.writeVariable(transactionParams)
                if self.graph.isCyclic():
                    if len(self.graph.cycleTransactions) > 1 or self.checkLoopInBlockedQueue():
                        print("Cycle found. Killing youngest transaction")
                        self.killTransaction = self.checkYoungestTransaction(self.graph)
                        self.abortTransaction(self.killTransaction)
                    elif self.checkLoopInBlockedQueue():
                        print("")
            elif typeOfTransaction == constants.READ:
                self.readVariable(transactionParams, False)
                if self.graph.isCyclic():
                    if len(self.graph.cycleTransactions) > 1 or self.checkLoopInBlockedQueue():
                        self.killTransaction = self.checkYoungestTransaction(self.graph)
                        self.abortTransaction(self.killTransaction)
                    elif self.checkLoopInBlockedQueue():
                        print("")
        elif typeOfTransaction == constants.END:
            transactionName = str(transactionParams[0])
            if transactionName not in self.abortedTransactions:
                    print("Committing Transaction" + transactionName)
                    self.endTransaction(self.transactionsDict[transactionName])
            else:
                print("Transaction was aborted can't commit.")

        else:
            print("Invalid command")
            return

    def writeVariable(self, transactionParams):
        """
        Responsible for processing write request. Obtains write lock for variable for this transaction,
        if lock couldn't be acquired its state is changed to blocked or waiting
        Adds transaction to blockedQueue or waitingTransactions appropriately
        :param transactionParams: parameters of the transaction parsed from input command
        """
        transactionName = transactionParams[0]
        variableToWrite = transactionParams[1]
        variableValue = int(transactionParams[2])
        if transactionName not in self.transactionsDict:
            print("Transaction not yet started.")
            return
        currentTransaction = self.transactionsDict[transactionName]
        state = currentTransaction.getTransactionState()

        if not (state == constants.TransactionState.running or state == constants.TransactionState.waiting):
            print("Transaction state isn't running or waiting")
            return
        if self.lockTable.checkTransactionHasLock(currentTransaction, variableToWrite, constants.LockType.write):
            print("Transaction " + transactionName + " already had the write lock on " + variableToWrite)
            currentTransaction.variablesToBeCommitted[variableToWrite] = variableValue
            currentTransaction.setTransactionState(constants.TransactionState.running)  # check if needed
            return

        # try to acquire write lock if the transaction didn't already have the lock
        acquireLock = self.siteManager.getLock(currentTransaction, constants.LockType.write, variableToWrite)
        if acquireLock == "GotLock":

            self.graph.addVertices(currentTransaction, variableToWrite)
            self.graph.addEdge(variableToWrite, currentTransaction)
            listOfWaitingTransactions = self.getFlattenedWaitingQueue()
            print("Transaction " + transactionName + " acquired write lock for " + variableToWrite)
            self.lockTable.setLock(currentTransaction, constants.LockType.write, variableToWrite)
            currentTransaction.variablesToBeCommitted[variableToWrite] = variableValue

            if transactionName in listOfWaitingTransactions:
                # if the transaction is waiting for a site and the variable its waiting
                # to write is different then return
                for waiting_transaction_tuple in listOfWaitingTransactions[transactionName]:
                    if waiting_transaction_tuple[1] != variableToWrite:
                        return
            currentTransaction.setTransactionState(constants.TransactionState.running)
        elif acquireLock == "NoSiteAvailable":
            # add to queue
            listOfWaitingTransactions = self.getFlattenedWaitingQueue()
            print("No Site is available for transaction " + str(currentTransaction.name) + " currently")
            waiting_transaction_tuple = (constants.WRITE, variableToWrite, variableValue)
            if transactionName in listOfWaitingTransactions:
                if waiting_transaction_tuple in listOfWaitingTransactions[transactionName]:
                    return
            print("Transaction" + transactionName + " is waiting for variable" + variableToWrite)
            currentTransaction.setTransactionState(constants.TransactionState.waiting)
            self.waitingTransactions[self.currentTime][currentTransaction.name] = waiting_transaction_tuple
        else:
            # elif acquireLock == "NoLockAvailable":
            print("Transaction couldn't get a write lock on this variable because a different transaction has a lock on it")
            self.graph.addEdge(currentTransaction, variableToWrite)
            for lock in self.siteManager.getAllLocksSet().lockDict[variableToWrite]:
                blockingTransaction = lock.transaction.name
                if lock.transaction == currentTransaction:
                    continue
                blockingTuple = (blockingTransaction, constants.WRITE, variableToWrite, variableValue)
                listOfBlockedTransactions = self.getFlattenedBlockedQueue()
                if currentTransaction.name in listOfBlockedTransactions:
                    if blockingTuple in listOfBlockedTransactions[currentTransaction.name]:
                        return
                currentTransaction.setTransactionState(constants.TransactionState.blocked)
                self.currentTime += 1
                self.blockedQueue[self.currentTime][currentTransaction.name] = blockingTuple

    def readVariable(self, transactionParams, flag= False):
        """
        Responsible for handling read requests. Obtains read locks on variables
        If can't acquire lock then transaction's status is changed to blocked or waiting
        Adds transactions blockedQueue or waitingTransactions appropriately
        :param transactionParams: parameters parsed from command
        :param flag: if true, then this was a waiting transaction and we try to give it a lock
        """
        transactionName = transactionParams[0]
        variableToRead = transactionParams[1]
        if transactionName not in self.transactionsDict:
            print("Transaction not yet begun")
            return

        currentTransaction = self.transactionsDict[transactionName]
        state = currentTransaction.getTransactionState()

        if not (state == constants.TransactionState.running or state == constants.TransactionState.waiting):
            return
        if currentTransaction.readOnly:
            self.readVariableRO(currentTransaction, variableToRead, transactionName, flag)
        else:
            # if this transaction already has a Write lock on the same variable, it will then read what it has itself
            # written
            if self.lockTable.checkTransactionHasLock(currentTransaction, variableToRead, constants.LockType.write):
                value = currentTransaction.variablesToBeCommitted[variableToRead]
                print(
                    "Transaction " + transactionName + " obtained read lock on " + variableToRead + " which has value" + str(
                        value))
                if variableToRead not in currentTransaction.readVar:
                    currentTransaction.readVar[variableToRead] = list()
                currentTransaction.readVar[variableToRead].append(value)
                return

            # if this transaction already has a Read lock on the same variable
            if self.lockTable.checkTransactionHasLock(currentTransaction, variableToRead, constants.LockType.read):
                self.lockTable.setLock(currentTransaction, constants.LockType.read, variableToRead)
                print(
                    "Transaction" + transactionName + "already has read lock on " + variableToRead + " which has value")
                currentTransaction.setTransactionState(constants.TransactionState.running)
                return

            # display that it cant get read lock cause it is waiting for another transaction that has a write lock
            for time in list(self.blockedQueue):
                transactionBlocked = self.blockedQueue[time]
                for transaction in list(transactionBlocked):
                    blockedTuple = transactionBlocked[transaction]
                    if len(blockedTuple) == 4 and blockedTuple[2] == variableToRead:
                        for lock in self.lockTable.lockDict[variableToRead]:
                            blockingTransaction = lock.transaction.name
                            if lock.transaction == currentTransaction:
                                continue
                            # if(lock.type!=constants.LockType.write):
                            #     continue
                            # blockingTuple = (blockingTransaction, constants.READ, variableToRead)
                            blockingTuple = (transaction, constants.READ, variableToRead)
                            currentTransaction.setTransactionState(constants.TransactionState.blocked)

                            self.blockedQueue[self.currentTime][currentTransaction.name] = blockingTuple
                            print("Transaction "+currentTransaction.name+" can't get read lock because "+transaction+" transaction is waiting for a write lock")
                            return
                                    
            # try to acquire lock on variable, GotLock -> noissues. GotLockRecoveringSite -> means that a read lock was given on a recovering site for unreplicated variable
            lockAcquireStatus = self.siteManager.getLock(currentTransaction, constants.LockType.read, variableToRead)
            if lockAcquireStatus == "GotLock" or lockAcquireStatus == "GotLockRecoveringSite":
                if lockAcquireStatus == "GotLock":
                    print(
                        "Transaction :" + transactionName + " got a read lock on variable:" + variableToRead + " which has value:" + str(
                            self.siteManager.getVariablesValues(variableToRead)))
                    # self.graph.addVertices(currentTransaction, variableToRead)
                else:
                    print(
                        "Site is recovering but since its the only copy a read lock was acquired, variable :" + variableToRead + " has value: " + str(
                            self.siteManager.getVariablesValues(variableToRead)))

                if variableToRead not in currentTransaction.readVar:
                    currentTransaction.readVar[variableToRead] = list()
                currentValueRead = self.siteManager.getVariablesValues(variableToRead)
                currentTransaction.readVar[variableToRead].append(currentValueRead)

                self.lockTable.setLock(currentTransaction, constants.LockType.read, variableToRead)
                self.graph.addEdge(variableToRead, currentTransaction)
                listOfWaitingTransaction = self.getFlattenedWaitingQueue()
                if currentTransaction.name in listOfWaitingTransaction:
                    for waitTuple in listOfWaitingTransaction[currentTransaction.name]:
                        if waitTuple[1] != variableToRead:
                            return
                # check if currenttransaction is in waiting transactions
                currentTransaction.setTransactionState(constants.TransactionState.running)
            elif lockAcquireStatus == "NoSiteAvailable":
                print("No Site available. Added to waiting queue")
                # add transaction to waiting transactions queue
                waitingTuple = (constants.READ, variableToRead)
                listOfWaitingTransaction = self.getFlattenedWaitingQueue()
                if currentTransaction.name in listOfWaitingTransaction:
                    if waitingTuple in listOfWaitingTransaction[currentTransaction.name]:
                        return
                self.waitingTransactions[self.currentTime][currentTransaction.name] = waitingTuple
                currentTransaction.setTransactionState(constants.TransactionState.waiting)
            else:
                print(
                    "Transaction is getting blocked by another transaction and is waiting for the other to release lock")
                self.graph.addEdge(currentTransaction, variableToRead)
                for lock in self.siteManager.getAllLocksSet().lockDict[variableToRead]:
                    blockingTransaction = lock.transaction.name
                    if lock.transaction == currentTransaction:
                        continue
                    blockingTuple = (blockingTransaction, constants.READ, variableToRead)
                    listOfBlockedTransaction = self.getFlattenedBlockedQueue()
                    if currentTransaction.name in listOfBlockedTransaction:
                        if blockingTuple in listOfBlockedTransaction[currentTransaction.name]:
                            return
                    print("Transaction " + currentTransaction.name+" is waiting for transaction "+blockingTransaction)
                    currentTransaction.setTransactionState(constants.TransactionState.blocked)
                    self.blockedQueue[self.currentTime][currentTransaction.name] = blockingTuple
                    self.currentTime +=1
        return

    def readVariableRO(self, currentTransaction, variableToRead, transactionName, flag):
        """
        Responsible for read operations for read only transactions
        :param currentTransaction: Transaction that is requesting read operation
        :param variableToRead: variable to be read
        :param transactionName: name of current transaction
        :param flag: if true we are trying to allow a waiting transaction read
        """
        # flag for transactions that were in waiting queue
        if flag:
            value = self.siteManager.getVariablesValues(variableToRead)
            if value is None:
                currentTransaction.variablesToBeCommitted[variableToRead] = value
            else:
                return
        if variableToRead in currentTransaction.writeVar.keys():
            if variableToRead not in currentTransaction.readVar:
                currentTransaction.readVar[variableToRead] = list()
            currentTransaction.readVar[variableToRead].append(currentTransaction.writeVar[variableToRead])
            print("Read only" + transactionName + " value " + variableToRead + " is :" + str(
                currentTransaction.writeVar[variableToRead]))
            # print("Read var:" + str(currentTransaction.readVar))
            listOfWaitingTransactions = self.getFlattenedWaitingQueue()

            if currentTransaction.name in listOfWaitingTransactions:
                # decide whether to return and not allow current to running state
                for waitingTuple in listOfWaitingTransactions[currentTransaction.name]:
                    if waitingTuple[1] != variableToRead:
                        return
            currentTransaction.setTransactionState(constants.TransactionState.running)
        else:
            print("Transaction is waiting. Add to waiting queue")
            waitingTuple = (constants.READ, variableToRead)
            listOfWaitingTransactions = self.getFlattenedWaitingQueue()
            if currentTransaction.name in listOfWaitingTransactions:
                if waitingTuple in listOfWaitingTransactions[currentTransaction.name]:
                    return
            currentTransaction.setTransactionState(constants.TransactionState.waiting)
            self.waitingTransactions[self.currentTime][currentTransaction.name] = waitingTuple

        return

    def endTransaction(self, transaction):
        """
        Responsible for ending transaction and calls release lock function to release its locks
        :param transaction: transaction to be ended
        """
        # if already aborted or committed then return
        status = self.transactionsDict[transaction.name].getTransactionState()
        if status == constants.TransactionState.aborted or status == constants.TransactionState.committed:
            return
        # Otherwise commit transaction
        # Write uncommitted variables onto the relevant sites
        uncommittedVariables = transaction.getVariablesToBeCommitted()
        for variable, value in uncommittedVariables.items():
            for i in range(1, 11):
                var = int(variable[1:])
                if var % 2 == 0 or ((var % 10) + 1) == i:
                    site = self.siteManager.getSite(i)
                    site.writeVariable(transaction, variable, value)
            self.graph.removeEdge(transaction)
        self.transactionsDict[transaction.name].setTransactionState(constants.TransactionState.committed)
        self.releaseLockForThisTransaction(transaction)

        #Remove from waiting/blocked queues
        transactionsWaitingReleased = list()
        transactionsBlockedReleased = list()
        blocked = self.getFlattenedBlockedQueue()
        if transaction.name in blocked:
            for time in sorted(self.blockedQueue.keys()):
                if transaction.name in self.blockedQueue[time]:
                    transactionsBlockedReleased.append((time, transaction.name))
                    self.blockedQueue[time].pop(transaction.name)

        for time in sorted(self.waitingTransactions.keys()):
            if transaction.name in self.waitingTransactions[time]:
                transactionsWaitingReleased.append((time, transaction.name))
                self.waitingTransactions[time].pop(transaction.name)

        #Try to change state of other transactions now that more locks have been released
        self.changeStateFromBlockedToWaiting()
        self.tryToExecuteWaitingTransactions()

    def checkAbortedTransaction(self):
        """
        Check if any transaction was marked aborted then abort it
        """
        for transactionName in list(self.transactionsDict):
            transaction = self.transactionsDict[transactionName]
            if transaction.name not in self.abortedTransactions:
                if transaction.getTransactionState() == constants.TransactionState.aborted:
                    print(
                        "Aborting transaction" + transaction.name + " and releasing its locks because it was flagged aborted.")
                    self.abortTransaction(transaction)

    def abortTransaction(self, transaction):
        """
        Aborts transaction, removed from queues and releases its locks
        :param transaction: transaction to be aborted
        """
        print("Aborting and clearing transaction" + transaction.name)
        transactionsWaitingReleased = list()
        transactionsBlockedReleased = list()
        for time in sorted(self.blockedQueue.keys()):
            if transaction.name in self.blockedQueue[time]:
                transactionsBlockedReleased.append((time, transaction.name))
                self.blockedQueue[time].pop(transaction.name)

        for time in sorted(self.waitingTransactions.keys()):
            if transaction.name in self.waitingTransactions[time]:
                transactionsWaitingReleased.append((time, transaction.name))
                self.waitingTransactions[time].pop(transaction.name)
        transaction.setTransactionState(constants.TransactionState.aborted)

        if transaction.name not in self.abortedTransactions:
            self.abortedTransactions[transaction.name] = transaction
            self.graph.removeEdge(transaction)
            if transaction in self.graph.cycleTransactions:
                self.graph.cycleTransactions.remove(transaction)
            # clear locks -
            self.releaseLockForThisTransaction(transaction)
        return

    def changeStateFromBlockedToWaiting(self):
        """
        Check if any transaction's state can be changed from blocked to waiting.
        If so change state and try to give it a lock
        """
        listChangeStateTransactions = []
        listOfBlockedTransactions = self.getFlattenedBlockedQueue()

        for time in sorted(self.blockedQueue.keys()):
            secondDict = list(self.blockedQueue[time])
            # print("check state :" + str(secondDict))

            for transaction in secondDict:
                blockedTuple = self.blockedQueue[time][transaction]
                flag = True
                # print("check state :" + str(blockedTuple))

                block = self.transactionsDict[blockedTuple[0]]
                checkAborted = block.getTransactionState() == constants.TransactionState.aborted
                checkCommitted = block.getTransactionState() == constants.TransactionState.committed
                flag = flag & (checkAborted or checkCommitted)

                if flag:
                    tupleToDelete = None
                    for blocker in listOfBlockedTransactions[transaction]:
                        if blocker[0] == block.name:
                            tupleToDelete = blocker
                            break
                    listOfBlockedTransactions[transaction].remove(tupleToDelete)
                    listChangeStateTransactions.append((time, transaction))
                    if len(listOfBlockedTransactions[transaction]) == 0:
                        flag = 0
                        listOfWaitingTransactions = self.getFlattenedWaitingQueue()

                        if transaction in listOfWaitingTransactions:
                            for waitTup in listOfWaitingTransactions[transaction]:
                                if waitTup == blockedTuple[1:]:
                                    flag = 1
                                    break
                        if flag:
                            continue
                        # print("Current time:" + str(self.currentTime))
                        self.waitingTransactions[self.currentTime][transaction] = blockedTuple[1:]
                        changedTransaction = self.transactionsDict[transaction]
                        # print("Changed state of transaction: "+str(changedTransaction.name))
                        if changedTransaction is not None:
                            self.graph.removeSpecificEdge(self.transactionsDict[changedTransaction.name], blockedTuple[2])

                        changedTransaction.setTransactionState(constants.TransactionState.waiting)

        for key in listChangeStateTransactions:
            self.blockedQueue[key[0]].pop(key[1])

    def releaseLockForThisTransaction(self, transaction):
        """
        Release lock for transaction, clears the locks it holds on all variables at all sites
        :param transaction: transaction releasing lock
        """
        lockDict = self.siteManager.getAllLocksSet().get_lockDict()
        print("Releasing site locks held by " + transaction.name)
        for variableName in sorted(list(lockDict)):
            locks = lockDict[variableName]
            for lock in locks:
                if lock.transaction == transaction:
                    self.siteManager.releaseLocks(lock, variableName)
                    # print("Released site locks for " + transaction.name + " variable" + variableName)
                    if self.lockTable.releaseLock(lock, variableName):
                        print("Released locks from lock table for " + transaction.name + " variable" + variableName)

    def checkYoungestTransaction(self, graph):
        """
        Finds youngest transaction in deadlock in the graph to kill
        :param graph: graph instance
        :return: transaction to be killed(youngest)
        """
        transactionsInCycle = sorted(self.graph.cycleTransactions, key=lambda x: x.startTime, reverse=True)
        print("Killing transaction :" + str(transactionsInCycle[0].name))
        return transactionsInCycle[0]

    def tryToExecuteWaitingTransactions(self):
        """
        Tries to execute transactions in the waiting queue
        """
        for time in list(self.waitingTransactions):
            waitingDict = self.waitingTransactions[time]

            for transactionName in list(waitingDict):
                params = waitingDict[transactionName]
                transaction = self.transactionsDict[transactionName]
                transaction.setTransactionState(constants.TransactionState.waiting)

                if params[0] == constants.WRITE:
                    self.writeVariable((transactionName, params[1], params[2]))
                elif params[0] == constants.READ:
                    self.readVariable((transactionName, params[1]))
                elif params[0] == constants.READ_ONLY:
                    self.readVariable((transactionName, params[1]), True)
                if self.transactionsDict[transactionName].getTransactionState() == constants.TransactionState.running:
                    self.waitingTransactions[time].pop(transactionName)

    def getFlattenedBlockedQueue(self):
        """
        Change time ordered dict and flatten to obtain list of dictionaries in blockedQueue
        :return: returns the flattened dict
        """
        listOfBlockedTransactions = defaultdict(list)
        for secondDict in self.blockedQueue.values():
            for transaction in list(secondDict):
                blockedTuple = secondDict[transaction]
                listOfBlockedTransactions[transaction].append(blockedTuple)
        return listOfBlockedTransactions

    def getFlattenedWaitingQueue(self):
        """
        Change time ordered dict and flatten to obtain list of dictionaries in waitingTRansaction
        :return: returns the flattened dict
        """
        listOfWaitingTransactions = defaultdict(list)
        for secondDict in self.waitingTransactions.values():
            for transaction in list(secondDict):
                waitTuple = secondDict[transaction]
                listOfWaitingTransactions[transaction].append(waitTuple)
        return listOfWaitingTransactions

    def checkLoopInBlockedQueue(self):
        """
        Checks if there is a loop in blocked queue
        :return: true if there is a deadlock else false
        """
        listOfBlockedTransactions = self.getFlattenedBlockedQueue()
        # print(listOfBlockedTransactions.keys())
        flag = False
        for t in listOfBlockedTransactions.keys():
            visited = dict()
            current = []
            # print(t)
            if self.findLoop(t, visited, current, listOfBlockedTransactions):
                flag = True
        if flag:
            return True
        else:
            False

    def findLoop(self, transaction, visited, current, blockedDictionary):
        """
        Finds the loop in blockedQueue and kills appropriate transaction
        :param transaction: transaction
        :param visited: visisted list for dfs
        :param current: current list
        :param blockedDictionary: list of blocked transactions
        :return: true if loop found else false
        """
        isAborted = self.transactionsDict[transaction].getTransactionState() == constants.TransactionState.aborted
        isCommitted = self.transactionsDict[transaction].getTransactionState() == constants.TransactionState.committed

        if transaction in blockedDictionary and not isAborted and not isCommitted:
            visited[transaction] = len(current) + 1
            current.append(transaction)
            for block in blockedDictionary[transaction]:
                # print("Block"+str(block[0]))
                block = block[0]
                if self.transactionsDict[block].getTransactionState() == constants.TransactionState.aborted:
                    continue
                if block in visited:
                    maxValue = -1
                    transactionList = current[(visited[block] -1):]
                    for name in transactionList:
                        t = self.transactionsDict[name]
                        # print(t.name)
                        if maxValue < t.startTime:
                            maxValue = t.startTime
                            self.killT = t
                    print("Found loop in blocked queue, killing: " + str(self.killT.name))
                    # print("Debug: youngest transaction" + self.checkYoungestTransaction(self.graph).name)
                    self.abortTransaction(self.killT)
                    return True
                else:
                    self.findLoop(block, visited, current, blockedDictionary)

