from timebuffer import TimeBuffer

class FloatTimeBuffer(TimeBuffer):

    def __init__(self):
        TimeBuffer.__init__(self)

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
    pass
