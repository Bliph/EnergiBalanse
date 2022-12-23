from .timebuffer import TimeBuffer

class FloatTimeBuffer(TimeBuffer):

    def __init__(self, age=-1, backup_filename=None):
        TimeBuffer.__init__(self, age, backup_filename)

    #################################################################
    # Get value
    # * 'inter'
    # * 'pre'
    # * 'post'
    # * 'avg'
    #
    def get_value(self, ts: int, selection='inter'):

        # Empty: Default to 0
        if len(self.sorted_list) <= 0:
            return 0
        
        idx = self.get_index(ts=ts)

        # Last value: Return last value
        if idx >= len(self.sorted_list):
            return self.sorted_list[len(self.sorted_list)-1][1]
        
        # First value: Return first value
        elif idx <= 0:
            return self.sorted_list[0][1]

        # Spot on
        elif self.sorted_list[idx][0] == ts:
            return self.sorted_list[idx][1]
     
        # Get index of values for idx-1 and idx+1
        pre_idx = max(0, idx-1)
        post_idx = min(idx, len(self.sorted_list)-1)

        pre = self.sorted_list[pre_idx]
        post = self.sorted_list[post_idx]

        if selection.lower() == 'pre':
            return pre[1]
        elif selection.lower() == 'post':
            return post[1]
        elif selection.lower() == 'avg':
            return (post[1]+pre[1])/2
        elif selection.lower() == 'inter':
            dt = post[0]-pre[0]
            dv = post[1]-pre[1]
            if dt == 0:
                return pre[1]
            else:
                return pre[1] + dv*(ts-pre[0])/dt
        else:
            return 0

    #################################################################
    # Integrate value over time
    #
    def integrate(self, ts_from: int, ts_to: int):

        if len(self.sorted_list) <= 0:
            return 0
            
        idx_from = self.get_index(ts=ts_from, valid_read_index=True)
        idx_to = self.get_index(ts=ts_to, valid_read_index=True)
        
        # End point not at ts
        if self.sorted_list[idx_to][0] > ts_to:
            idx_to = max(idx_from, idx_to-1)

        pre_value = self.get_value(ts=ts_from, selection='pre')
        post_value = self.get_value(ts=ts_to, selection='pre')

        sum = 0
        for idx in range(idx_from, idx_to):
            sum += self.sorted_list[idx][1] * (self.sorted_list[idx+1][0] - self.sorted_list[idx][0])

        sum += pre_value * (self.sorted_list[idx_from][0] - ts_from)
        sum += post_value * (ts_to - self.sorted_list[idx_to][0])

        return sum

    #################################################################
    # Average value over time
    #
    def avg(self, ts_from: int, ts_to: int):
        
        dt = ts_to - ts_from
        if dt == 0:
            return 0
        else:
            return self.integrate(ts_from=ts_from, ts_to=ts_to)/dt







if __name__ == '__main__':

    import time
    import random

    a = FloatTimeBuffer() 
    for i in range(10):
        a.insert_sorted(ts = int(random.random()*10), value=int(random.random()*100)) 

    x1 = a.get_value(5.5, 'pre')
    x2 = a.get_value(5.5, 'post')
    x3 = a.get_value(5.5, 'avg')
    x4 = a.get_value(5.5, 'inter')

    a = FloatTimeBuffer() 
    a.insert_sorted(ts=1, value=35) 
    a.insert_sorted(ts=3, value=234) 
    a.insert_sorted(ts=4, value=5) 
    a.insert_sorted(ts=7, value=-5) 
    a.insert_sorted(ts=8, value=70) 
    a.insert_sorted(ts=9, value=71) 

    z1 = a.integrate(3, 8)
    z2 = a.avg(3, 8)

    y0 = a.integrate(0, 3.99)
    y1 = a.integrate(2.5, 8.2)
    y2 = a.avg(2.5, 8.2)
    
    pass

