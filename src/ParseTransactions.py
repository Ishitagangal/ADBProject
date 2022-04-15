import os

import Variable
from .Transaction import Transaction


class ParseTransactions:

    def __init__(self, file, site_manager, transaction_manager,lock_table):
        self.file = file
        self.siteManager = site_manager
        self.transactionManager = transaction_manager
        self.lockTable = lock_table
        self.lines = self.getLine()

    def getLine(self):
        with open(self.file, 'r') as test_file:
            for line in test_file:
                if len(line) > 1:
                    yield line

    def getNextTransaction(self):
        line = next(self.lines, None)
        if line is None:
            return line
        else:
            return self.processTransaction(line)

    def processTransaction(self, line):
        line = line.strip().split("\n")
        transactions = []
        for t in line:
            if t.find("//") == 0:
                continue
            transactions.append(Transaction(t))
        return transactions

    def parseFileTransactions(self):
        transactions = self.getNextTransaction()
        while transactions is not None:
            for t in transactions:
                if t.transactionType in ["recover","fail"]:
                    continue #site manager call
                else:
                    continue # transaction manager call
            transactions = self.getNextTransaction()



