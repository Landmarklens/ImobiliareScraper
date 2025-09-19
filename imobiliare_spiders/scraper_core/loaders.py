from scrapy.loader import ItemLoader
from itemloaders.processors import Join, MapCompose, TakeFirst, Identity
from w3lib.html import remove_tags
from .items import ListingItem
from .helper import convert_to_numeric


def filter_empty(_s):
    return _s or None


class ListingLoader(ItemLoader):
    default_item_class = ListingItem
    # default_input_processor = MapCompose()
    default_output_processor = TakeFirst()

    description_in = MapCompose(remove_tags, str.strip, filter_empty)
    description_out = Join(" ")
    address_in = MapCompose(remove_tags, str.strip, filter_empty)
    address_out = Join(" ")

    floor_in = MapCompose(remove_tags, str.strip, filter_empty)
    floor_out = Join()

    external_id_in = MapCompose(remove_tags)
    # title_in = MapCompose(remove_tags)
    title_in = MapCompose(remove_tags, str.strip)
    property_type_in = MapCompose(str.lower, remove_tags)

    room_count_in = MapCompose(convert_to_numeric)
    bathroom_count_in = MapCompose(convert_to_numeric)
    furnished_in = Identity()
    parking_in = Identity()

    def __init__(self, response):
        super(ListingLoader, self).__init__(response=response)
        # self.images_in = MapCompose(response.urljoin)
        self.images_in = MapCompose(response.urljoin, str.strip)  # PK
