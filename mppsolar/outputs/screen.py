import logging

log = logging.getLogger('MPP-Solar')


class screen():
    def __init__(self, *args, **kwargs) -> None:
        log.debug(f'processor.screen __init__ kwargs {kwargs}')

    def output(self, data=None, tag=None, mqtt_broker=None):
        log.info('Using output processor: screen')
        if not data:
            return
        print(f"{'Parameter':<30}\t{'Value':<15} Unit")
        for key in data:
            value = data[key][0]
            unit = data[key][1]
            print(f'{key:<30}\t{value:<15}\t{unit:<4}')