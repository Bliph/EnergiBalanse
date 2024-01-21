import logging
from threading import Thread
import time
import copy
# import json
import yaml

class TimeBuffer:

    def __init__(self, age=-1, backup_filename=None, backup_interval=60):
        self.sorted_list = []
        self.age = age
        self.backup_interval=backup_interval
        self.backup_filename=backup_filename
        self.logger = logging.getLogger('timebuffer')
        if backup_filename is not None:
            self.restore()

    #################################################################
    # Kicker tread loop
    #
    def save_runner(self):
        if self.backup_filename is not None:
            try:
                with open(self.backup_filename, "w") as f:
                    f.write(yaml.dump(self.sorted_list))
#                    f.write(yaml.dump(json.loads(json.dumps(self.sorted_list))))
            except Exception as e:
                self.logger.warning('Could not write buffer backup {}: {}'.format(self.backup_filename, e))


    #################################################################
    # Restore data from backup
    #
    def restore(self):
        if self.backup_filename is not None:
            try:
                with open(self.backup_filename, "r") as f:
                    restore_list = yaml.safe_load(f)
                    if type(restore_list) is list:
                        self.sorted_list = restore_list
            except Exception as e:
                self.logger.warning('Could not read buffer backup {}: {}'.format(self.backup_filename, e))

    #################################################################
    # Save data to backup
    #
    def save(self):
        t = Thread(target=self.save_runner, daemon=True)
        t.start()

    #################################################################
    # Auto crop data to max age
    #
    def auto_crop(self):
        if self.age > 0 and self.sorted_list[0][0] < time.time()-self.age:
            self.crop_interval(from_ts=time.time()-self.age-1, to_ts=int(time.time()+1))

    #################################################################
    # Return last tuple in list. None if empty
    #
    def get_last_tuple(self):
        # Empty list:
        if len(self.sorted_list) <= 0:
            return None
        else:
            return self.sorted_list[-1]

    #################################################################
    # Find index for tuple with ts >= provided ts
    #
    def get_index(self, ts: int, from_idx=0, to_idx=None, valid_read_index=False):

        # Empty list:
        if len(self.sorted_list) <= 0:
            return 0

        # Clamp indexes, default: whole list
        from_idx = min(max(from_idx, 0), len(self.sorted_list)-1)
        if to_idx is None:
            to_idx = len(self.sorted_list) - 1
        else:
            to_idx = max(min(to_idx, len(self.sorted_list)-1), 0)

        # Before first element
        if ts <= self.sorted_list[from_idx][0]:
            return from_idx

        # After last element
        elif ts > self.sorted_list[to_idx][0]:
            if not valid_read_index:
                return to_idx + 1
            else:
                return to_idx

        # Smallest possible interval (int)
        elif to_idx - from_idx <= 1:
            return to_idx

        # Recurse, binary search
        else:

            # Middle index
            m_idx = from_idx + int((to_idx - from_idx)/2)

            # Spot on
            if ts == self.sorted_list[m_idx][0]:
                return m_idx

            # Lower half
            elif ts < self.sorted_list[m_idx][0]:
                return self.get_index(ts, from_idx=from_idx, to_idx=m_idx, valid_read_index=valid_read_index)

            # Upper half
            elif ts > self.sorted_list[m_idx][0]:
                return self.get_index(ts, from_idx=m_idx, to_idx=to_idx, valid_read_index=valid_read_index)

    #################################################################
    # Insert a element and keep list sorted by ts
    #
    def insert_sorted(self, ts: int, value, overwrite=True):
        vt = [ts, value]        # Use list as a tuple to make it yaml-comp
        idx = self.get_index(ts)

        if overwrite and \
            len(self.sorted_list) > 0 and \
            idx < len(self.sorted_list) and \
            idx >= 0 and \
            self.sorted_list[idx][0] == ts:
            self.sorted_list[idx] = vt
        else:
            self.sorted_list.insert(idx, vt)

        self.auto_crop()
        self.save()

    #################################################################
    # Return list [from, to], including
    #
    def get_interval(self, from_ts=0, to_ts=0):
        if len(self.sorted_list) <= 0:
            return []

        # Default: whole list
        if to_ts <= 0:
            to_ts = self.sorted_list[-1:][0][0]

        from_idx = self.get_index(ts=from_ts)
        to_idx = self.get_index(ts=to_ts)

        # If to_ts is at last element of range, include last element
        if to_idx < len(self.sorted_list) and to_ts == self.sorted_list[to_idx][0]:
            to_idx += 1

        return copy.deepcopy(self.sorted_list[from_idx:to_idx])

    #################################################################
    # Crop list [from, to], including
    #
    def crop_interval(self, from_ts=0, to_ts=0):
        self.sorted_list = self.get_interval(from_ts=from_ts, to_ts=to_ts)


if __name__ == '__main__':
    import time
    import random

    a = TimeBuffer()
    a.insert_sorted(ts = int(time.time()*1000), value='a')
    time.sleep(random.random())
    a.insert_sorted(ts = int(time.time()*1000), value='b')
    time.sleep(random.random())
    a.insert_sorted(ts = int(time.time()*1000), value='c')

    aa = a.get_index(a.sorted_list[1][0]-1)
    bb = a.get_index(a.sorted_list[1][0])
    cc = a.get_index(a.sorted_list[1][0]+1)

    a.insert_sorted(ts=a.sorted_list[1][0]+1, value='b_post')
    a.insert_sorted(ts=a.sorted_list[1][0], value='b_at')
    a.insert_sorted(ts=a.sorted_list[1][0]-1, value='b_pre')

    x = a.get_index(ts=a.sorted_list[-1:][0][0])

    l = a.get_interval()
    l = a.get_interval(from_ts=a.sorted_list[1][0], to_ts=a.sorted_list[1][0])
    l = a.get_interval(from_ts=a.sorted_list[1][0], to_ts=a.sorted_list[2][0])
    l = a.get_interval(from_ts=a.sorted_list[1][0], to_ts=a.sorted_list[3][0])

    a.sorted_list = []
    l = a.get_interval(10, 20)

    a.insert_sorted(ts=30, value='x')
    l = a.get_interval(10, 20)

    pass
