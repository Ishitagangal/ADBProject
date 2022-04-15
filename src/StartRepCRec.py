import argparse
from pathlib import Path

from Site import Site
from Variable import Variable


def main():
    parser = argparse.ArgumentParser(description='ADB project')
    parser.add_argument('--filePath', type=str,
                        help="path to file which has the instructions")
    parser.add_argument('--num_sites', type=int, default=10,
                        help='Number of sites')
    parser.add_argument('--num_Var', type=int, default=20,
                        help='number of variables')
    parser.add_argument('--outFile', type=str,
                        help='Output file, if not passed default to stdout')

    args = parser.parse_args()
    print(args.num_sites)
    p = Path('.')
    p = p / args.filePath
    if args.outFile:
        open(args.outFile, 'w').close()


if __name__ == '__main__':

    main()
    variablesList = []
    for i in range(1, 21):
        variablesList.append(Variable('x' + str(i), 10 * i))

    siteList = []
    for i in range(1, 11):
        for j in range(1, 21):
            if j % 2 == 0:
                siteList.append(Site(str(j)))
            else:
                siteList.append(Site(str(j + 1)))

