import re


class Transaction:

    pattern = "\((.*?)\)"

    def __init__(self, transaction):
        self.transactionType = (transaction.split('(')[0]).strip(" ")
        self.transactionParameters = re.search(self.pattern,transaction).group()
        self.transactionParameters = self.transactionParameters.strip('()')
        self.transactionParameters = map(lambda x: x.strip(), self.transactionParameters.split(','))
        # char type
        # state

    def get_transactionType(self):

        return self.transactionType

    def get_transactionParameters(self):

        return self.transactionParameters