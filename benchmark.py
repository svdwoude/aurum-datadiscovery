import time
from dataanalysis import dataanalysis as da

def test_num_sim(col1, col2, it):
    start = time.time()
    for i in range(it):
        sim = da.compare_pair_num_columns(col1, col2)
    end = time.time()
    total = end - start
    print("Num sim for iterations: "+str(it)+" took: "+str(total))

def test_text_sim(col1, col2, it):
    start = time.time()
    for i in range(it):
        #sim = da.compare_pair_text_columns(col1, col2)
        sim = da._compare_text_columns_dist(col1, col2)
    end = time.time()
    total = end - start
    print("Text sim for iterations: "+str(it)+" took: "+str(total))

if __name__ == "__main__":
    col2 = col1
    it = 10
    #test_num_sim(col1, col2, it)
    test_text_sim(col1, col2, it)