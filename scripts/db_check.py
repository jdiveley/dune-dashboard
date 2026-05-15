import sys, psycopg2
try:
    host = 'localhost'
    port = int(sys.argv[1])
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == '-host' and i + 1 < len(sys.argv):
            host = sys.argv[i + 1]
            i += 2
        else:
            i += 1
    c = psycopg2.connect(host=host, port=port, user='postgres', password='postgres', dbname='dune', connect_timeout=3)
    c.close()
    print('ok')
except:
    pass