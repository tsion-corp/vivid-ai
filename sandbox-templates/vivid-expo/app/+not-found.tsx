import { Link } from "expo-router";
import { Text, View } from "react-native";

export default function NotFoundScreen() {
  return (
    <View className="flex-1 items-center justify-center bg-background px-6 dark:bg-background-dark">
      <Text className="text-xl font-semibold text-foreground dark:text-foreground-dark">
        This screen does not exist.
      </Text>
      <Link href="/" className="mt-4 text-base text-primary">
        Go to the home screen
      </Link>
    </View>
  );
}
