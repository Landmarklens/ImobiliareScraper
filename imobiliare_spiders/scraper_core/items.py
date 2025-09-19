# Define here the models for your scraped items
#
# See documentation in:
# https://docs.scrapy.org/en/latest/topics/items.html

import scrapy


class ListingItem(scrapy.Item):
    external_source = scrapy.Field()  # required
    external_link = scrapy.Field()  # required
    external_id = scrapy.Field()
    title = scrapy.Field()
    description = scrapy.Field()
    property_type = scrapy.Field()  # required
    square_meters = scrapy.Field()  # required
    room_count = scrapy.Field()
    bathroom_count = scrapy.Field()
    rent_string = scrapy.Field()
    rent = scrapy.Field()
    available_date = scrapy.Field()
    deposit = scrapy.Field()
    prepaid_rent = scrapy.Field()
    currency = scrapy.Field()
    external_images_count = scrapy.Field()

    address = scrapy.Field()  # required
    city = scrapy.Field()  # required
    zipcode = scrapy.Field()  # required
    latitude = scrapy.Field()  # required
    longitude = scrapy.Field()  # required
